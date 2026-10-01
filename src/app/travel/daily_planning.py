"""Conservative, data-aware daily scheduling for verified Geoapify places.

Geoapify place search does not normally return visit lengths or route travel
times.  This module therefore keeps those facts separate from planning
estimates: a duration supplied by a future external source is retained as
verified data; otherwise a deliberately conservative category-based estimate
is used and labelled as such.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any, Iterable

from app.travel.mobility import MobilityProfile
from app.travel.routing import RoutingService, UnavailableRoutingService
from app.travel.itinerary import day_date, place_snapshot, timeline_item
from app.travel.constraints import TripConstraints


class DailyPlanner:
    """Turn an LLM-selected itinerary into a realistic, non-overlapping plan."""

    day_start_minutes = 10 * 60
    day_window_minutes = 9 * 60
    reserved_break_minutes = 90

    def __init__(self, routing_service: RoutingService | None = None) -> None:
        self.routing_service = routing_service or UnavailableRoutingService()

    def plan(
        self,
        itinerary: list[dict[str, Any]],
        real_activities: Iterable[dict[str, Any]],
        intents: Iterable[Any],
        preferences: dict[str, Any],
        destination: dict[str, Any],
        mobility_profile: MobilityProfile | None = None,
        accommodation: dict[str, Any] | None = None,
        constraints: TripConstraints | None = None,
    ) -> None:
        """Schedule selected activities, dropping only activities that cannot fit.

        The LLM remains responsible for selecting real places.  This planner
        applies a conservative time budget afterwards, so no fixed activity
        count is imposed and each day can have a different number of places.
        """
        del destination  # No unverified assumptions are made from a city name alone.
        activities_by_name = {
            item["name"].casefold(): item
            for item in real_activities
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        constraints = constraints or TripConstraints()
        # A later requested start is a real scheduling constraint, rather than
        # merely a label in the plan summary.  Never schedule before the
        # planner's conservative default start.
        effective_day_start = max(
            self.day_start_minutes,
            constraints.preferred_start_minutes or self.day_start_minutes,
        )
        daily_budget = self._daily_activity_budget(intents, preferences)
        if constraints.min_daily_free_minutes is not None:
            daily_budget = min(daily_budget, self.day_window_minutes - constraints.min_daily_free_minutes)
        if constraints.preferred_end_minutes is not None and constraints.preferred_end_minutes > effective_day_start:
            daily_budget = min(daily_budget, constraints.preferred_end_minutes - effective_day_start)
        for day in itinerary:
            if not isinstance(day, dict):
                continue
            mode = mobility_profile.planning_mode() if mobility_profile else None
            if mobility_profile and mobility_profile.mixed_strategy and mobility_profile.allows("car"):
                for activity in day.get("activities", []):
                    place = activities_by_name.get(str(activity.get("name", "")).casefold()) if isinstance(activity, dict) else None
                    if isinstance(place, dict) and isinstance(accommodation, dict):
                        try:
                            distance = self._distance_km(float(place["latitude"]), float(place["longitude"]), float(accommodation["latitude"]), float(accommodation["longitude"]))
                        except (KeyError, TypeError, ValueError):
                            continue
                        if distance > 5:
                            mode = "car"
                            break
            self._plan_day(day, activities_by_name, daily_budget, mobility_profile, accommodation, preferences, constraints, effective_day_start, mode)

    def _plan_day(
        self,
        day: dict[str, Any],
        activities_by_name: dict[str, dict[str, Any]],
        daily_budget: int,
        mobility_profile: MobilityProfile | None,
        accommodation: dict[str, Any] | None,
        preferences: dict[str, Any],
        constraints: TripConstraints,
        day_start_minutes: int,
        travel_mode: str | None,
    ) -> None:
        original_activities = day.get("activities", [])
        if not isinstance(original_activities, list):
            return

        scheduled: list[dict[str, Any]] = []
        meals: list[dict[str, Any]] = []
        elapsed = 0
        previous_place: dict[str, Any] | None = accommodation
        lunch_added = False
        idle_wait = 0
        verified_travel = 0
        for activity in original_activities:
            # This is intentionally a cap rather than a fixed activity rule:
            # quiet days may still contain fewer activities when duration,
            # route, or free-time constraints require it.
            if (
                constraints.preferred_activity_count is not None
                and len(scheduled) >= constraints.preferred_activity_count
            ):
                break
            if not isinstance(activity, dict):
                continue
            name = activity.get("name")
            real_place = activities_by_name.get(name.casefold()) if isinstance(name, str) else None
            duration, duration_status, duration_source = self._duration_for(real_place)
            # ORS has no motorcycle profile. Its car profile supplies a road
            # distance proxy only; motorcycle legality and travel time remain
            # unavailable as motorcycle-specific facts.
            route_mode = "car" if travel_mode == "motorcycle" else travel_mode
            route = self.routing_service.route(previous_place, real_place, route_mode) if previous_place and real_place else None
            if route and route.data_status == "verified" and route.duration_minutes is not None:
                transition = route.duration_minutes
                transition_status = "verified"
            else:
                transition = self._transition_buffer(previous_place, real_place) if previous_place else 0
                transition_status = "estimated" if transition else "not_applicable"
            # Lunch is a time window, not a second consecutive activity.  Keep
            # it broadly around midday and leave a visible gap when a morning
            # activity finishes early. Food choices are attached later from
            # verified Geoapify records.
            projected_start = day_start_minutes + elapsed + transition
            lunch_minutes = constraints.meal_duration_minutes or 60
            meal_before = 0
            lunch_wait = 0
            if not lunch_added and (projected_start >= 12 * 60 or scheduled and projected_start + duration > 12 * 60):
                lunch_start = max(day_start_minutes + elapsed, 12 * 60)
                lunch_wait = lunch_start - (day_start_minutes + elapsed)
                meal_before = lunch_wait + lunch_minutes
            # ``daily_budget`` is the activity-and-transition capacity retained
            # from Phase 4.2; the explicit lunch allowance must not silently
            # reduce the previous variable-activity behaviour.
            proposed_verified_travel = verified_travel + (route.duration_minutes if route and route.data_status == "verified" and route.duration_minutes is not None else 0)
            return_route = (
                self.routing_service.route(real_place, accommodation, route_mode)
                if constraints.max_daily_travel_minutes is not None and real_place and accommodation else None
            )
            if return_route and return_route.data_status == "verified" and return_route.duration_minutes is not None:
                proposed_verified_travel += return_route.duration_minutes
            schedule_limit = daily_budget if constraints.min_daily_free_minutes is not None else daily_budget + 60
            travel_cap_exceeded = constraints.max_daily_travel_minutes is not None and proposed_verified_travel > constraints.max_daily_travel_minutes
            projected_elapsed = elapsed + meal_before + transition + duration
            time_budget_exceeded = projected_elapsed - idle_wait - lunch_wait > schedule_limit or projected_elapsed > self.day_window_minutes
            if (travel_cap_exceeded and scheduled) or time_budget_exceeded:
                # Keep the day deliberately under-filled.  A later phase may offer
                # alternative real places, but this phase must not invent one.
                continue
            if travel_cap_exceeded:
                # A validated itinerary requires a factual place each day.
                # Retain one real activity rather than silently dropping the
                # day; Plan fit will disclose that this travel cap is not met.
                day["travel_constraint_note"] = "No verified activity fits the daily travel limit; the closest valid day remains and the limit is partially satisfied."
            if meal_before:
                meal_start = day_start_minutes + elapsed
                meal_start += lunch_wait
                meals.append(self._meal("lunch", meal_start, lunch_minutes))
                elapsed += meal_before
                idle_wait += lunch_wait
                lunch_added = True
            start = day_start_minutes + elapsed + transition
            end = start + duration
            activity["duration_minutes"] = duration
            activity["duration_data_status"] = duration_status
            activity["duration_source"] = duration_source
            activity.update(place_snapshot(real_place))
            activity["travel_time_minutes"] = route.duration_minutes if route and route.data_status == "verified" else None
            activity["travel_time_data_status"] = "verified" if route and route.data_status == "verified" else "unavailable"
            activity["route"] = route.to_dict() if route else None
            activity["requested_transport_mode"] = travel_mode
            activity["route_mode_note"] = "Car-road profile; motorcycle suitability unverified" if travel_mode == "motorcycle" else None
            activity["transition_buffer_minutes_before"] = transition
            activity["transition_buffer_status"] = transition_status
            activity["start_time"] = self._format_time(start)
            activity["end_time"] = self._format_time(end)
            scheduled.append(activity)
            elapsed += transition + duration
            # The next stop replaces this candidate's return-to-hotel leg.
            verified_travel = proposed_verified_travel - (
                return_route.duration_minutes if return_route and return_route.data_status == "verified" and return_route.duration_minutes is not None else 0
            )
            previous_place = real_place

        day["activities"] = scheduled
        # A short morning activity still gets a midday lunch block.  The gap
        # before it remains free time rather than an invented activity.
        if scheduled and not lunch_added:
            meal_minutes = constraints.meal_duration_minutes or 60
            lunch_start = max(day_start_minutes + elapsed, 12 * 60)
            if lunch_start + meal_minutes <= day_start_minutes + self.day_window_minutes:
                meals.append(self._meal("lunch", lunch_start, meal_minutes))
                elapsed += (lunch_start - (day_start_minutes + elapsed)) + meal_minutes
                lunch_added = True
        # Dinner must be materially later than lunch.  When no further
        # verified activity is available, schedule an evening meal rather than
        # incorrectly placing it immediately after the midday block.
        if scheduled:
            meal_minutes = constraints.meal_duration_minutes or 60
            dinner_start = max(day_start_minutes + elapsed, 18 * 60)
            if dinner_start + meal_minutes <= day_start_minutes + self.day_window_minutes:
                meals.append(self._meal("dinner", dinner_start, meal_minutes))
                elapsed += (dinner_start - (day_start_minutes + elapsed)) + meal_minutes
        day["date"] = day_date(preferences, int(day.get("day", 1)))
        day["meals"] = meals
        day["items"] = self._timeline_items(scheduled, meals, accommodation, day_start_minutes)
        if scheduled and accommodation:
            route_mode = "car" if travel_mode == "motorcycle" else travel_mode
            day["return_route"] = self.routing_service.route(scheduled[-1], accommodation, route_mode).to_dict()
        else:
            day["return_route"] = None
        route_stops = [place_snapshot(accommodation), *[place_snapshot(item) for item in scheduled]]
        if accommodation:
            route_stops.append(place_snapshot(accommodation))
        day["route_stops"] = [stop for stop in route_stops if stop]
        # ``elapsed`` also includes deliberate waiting for a realistic meal
        # window. Waiting is free time, not activity workload, so report it
        # separately rather than making a relaxed day appear fully booked.
        committed_minutes = (
            sum(item["duration_minutes"] for item in scheduled)
            + sum(item.get("duration_minutes", 0) for item in meals)
            + sum(item["transition_buffer_minutes_before"] for item in scheduled)
        )
        day["schedule"] = {
            "planned_transport_mode": travel_mode,
            "day_start_minutes": day_start_minutes,
            "daily_activity_budget_minutes": daily_budget,
            "scheduled_activity_minutes": sum(item["duration_minutes"] for item in scheduled),
            "reserved_break_minutes": self.reserved_break_minutes,
            "reserved_transition_buffer_minutes": sum(
                item["transition_buffer_minutes_before"] for item in scheduled
            ),
            "free_time_minutes": max(self.day_window_minutes - committed_minutes, 0),
            "planning_data_status": "estimated",
            "note": (
                "Visit lengths are planning estimates unless explicitly marked as verified. "
                "Route times are verified only when the route record says so; otherwise "
                "the transition buffer is a planning estimate."
            ),
        }

    @staticmethod
    def _meal(meal_type: str, start: int, duration: int = 60) -> dict[str, Any]:
        return {
            "meal_type": meal_type,
            "start_time": DailyPlanner._format_time(start),
            "end_time": DailyPlanner._format_time(start + duration),
            "duration_minutes": duration,
            "duration_data_status": "estimated",
            "duration_source": "Conservative planning meal allowance; restaurant duration unavailable",
            "options": [],
            "options_status": "unavailable",
        }

    def _timeline_items(
        self,
        scheduled: list[dict[str, Any]],
        meals: list[dict[str, Any]],
        accommodation: dict[str, Any] | None,
        day_start_minutes: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if accommodation:
            items.append(timeline_item("accommodation", start_time=self._format_time(day_start_minutes), source="Geoapify", **place_snapshot(accommodation)))
        entries: list[tuple[str, dict[str, Any]]] = [("activity", value) for value in scheduled] + [("meal", value) for value in meals]
        entries.sort(key=lambda item: item[1].get("start_time", "99:99"))
        for item_type, value in entries:
            if item_type == "activity":
                route = value.get("route")
                if isinstance(route, dict):
                    travel_status = route.get("data_status", "unavailable")
                    duration = route.get("duration_minutes") if travel_status == "verified" else value.get("transition_buffer_minutes_before")
                    items.append(timeline_item(
                        "travel", start_time=self._travel_start(value), end_time=value.get("start_time"), duration_minutes=duration,
                        transport_mode=route.get("transport_mode"), travel_distance_meters=route.get("distance_meters") if travel_status == "verified" else None,
                        travel_duration_minutes=route.get("duration_minutes") if travel_status == "verified" else None,
                        travel_time_data_status=travel_status, source=route.get("source"),
                        requested_transport_mode=value.get("requested_transport_mode"),
                        route_mode_note=value.get("route_mode_note"),
                        planning_buffer_minutes=value.get("transition_buffer_minutes_before") if travel_status != "verified" else None,
                        origin=place_snapshot(route.get("origin")), destination=place_snapshot(route.get("destination")),
                    ))
                items.append(timeline_item("activity", start_time=value.get("start_time"), end_time=value.get("end_time"), duration_minutes=value.get("duration_minutes"), duration_data_status=value.get("duration_data_status"), source=value.get("duration_source"), reason=value.get("reason"), **place_snapshot(value)))
            else:
                items.append(timeline_item("meal", start_time=value.get("start_time"), end_time=value.get("end_time"), duration_minutes=value.get("duration_minutes"), meal_type=value.get("meal_type"), duration_data_status=value.get("duration_data_status"), source=value.get("duration_source"), options=value.get("options", []), options_status=value.get("options_status")))
        if scheduled or meals:
            timed_ends = [entry.get("end_time") for entry in [*scheduled, *meals] if isinstance(entry.get("end_time"), str)]
            last_end = max(timed_ends, key=self._time_to_minutes) if timed_ends else None
            if isinstance(last_end, str):
                free = max(self.day_window_minutes - (self._time_to_minutes(last_end) - day_start_minutes), 0)
                if free:
                    items.append(timeline_item("free_time", start_time=last_end, duration_minutes=free, source="planning estimate"))
        return items

    @staticmethod
    def _travel_start(activity: dict[str, Any]) -> str | None:
        start = activity.get("start_time")
        duration = activity.get("travel_time_minutes") or activity.get("transition_buffer_minutes_before")
        if not isinstance(start, str) or not isinstance(duration, int):
            return None
        return DailyPlanner._format_time(DailyPlanner._time_to_minutes(start) - duration)

    @staticmethod
    def _time_to_minutes(value: str) -> int:
        hour, minute = value.split(":")
        return int(hour) * 60 + int(minute)

    @classmethod
    def _daily_activity_budget(cls, intents: Iterable[Any], preferences: dict[str, Any]) -> int:
        """Leave meaningful unallocated time; strong relaxation lowers capacity."""
        budget = 330
        for intent in intents:
            concept = str(getattr(intent, "concept", "")).casefold()
            strength = str(getattr(intent, "strength", "low")).casefold()
            polarity = str(getattr(intent, "polarity", "positive")).casefold()
            if polarity != "positive":
                continue
            weight = {"very_high": 2, "high": 1, "medium": 1, "low": 0}.get(strength, 0)
            if any(term in concept for term in ("relax", "spa", "wellness", "beach", "swim")):
                budget -= 60 + 30 * weight
            elif any(term in concept for term in ("active", "adventure", "hiking", "sightseeing", "walking")):
                budget += 30 + 30 * weight
        travel_style = str(preferences.get("travel_style", "")).casefold()
        if any(term in travel_style for term in ("relaxed", "slow", "leisure")):
            budget -= 45
        elif any(term in travel_style for term in ("active", "fast", "intensive")):
            budget += 45
        return max(180, min(budget, 450))

    @classmethod
    def _duration_for(cls, place: dict[str, Any] | None) -> tuple[int, str, str]:
        if isinstance(place, dict):
            external_duration = place.get("duration_minutes")
            if isinstance(external_duration, (int, float)) and 0 < external_duration <= 720:
                source = place.get("duration_source")
                return int(external_duration), "verified", str(source or "external place data")
            categories = " ".join(str(item).casefold() for item in place.get("categories", []))
        else:
            categories = ""
        if any(term in categories for term in ("spa", "wellness")):
            minutes = 180
        elif any(term in categories for term in ("swimming", "beach", "water")):
            minutes = 150
        elif "museum" in categories:
            minutes = 120
        elif any(term in categories for term in ("hiking", "sport", "outdoor.activity")):
            minutes = 120
        elif any(term in categories for term in ("restaurant", "catering", "food")):
            minutes = 75
        elif any(term in categories for term in ("park", "garden", "nature")):
            minutes = 75
        else:
            minutes = 90
        return minutes, "estimated", "Conservative AI planning estimate; Geoapify duration unavailable"

    @classmethod
    def _transition_buffer(cls, previous: dict[str, Any] | None, current: dict[str, Any] | None) -> int:
        """Use a labelled planning buffer, never a claimed route-travel time."""
        if not previous or not current:
            return 20
        try:
            distance = cls._distance_km(
                float(previous["latitude"]), float(previous["longitude"]),
                float(current["latitude"]), float(current["longitude"]),
            )
        except (KeyError, TypeError, ValueError):
            return 20
        if distance <= 2:
            return 15
        if distance <= 8:
            return 25
        return 40

    @staticmethod
    def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius = 6371.0
        d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
        a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
        return 2 * radius * asin(sqrt(a))

    @staticmethod
    def _format_time(minutes: int) -> str:
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
