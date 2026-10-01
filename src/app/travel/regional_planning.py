"""Preference-aware regional days built only from discovered places and routes."""

from __future__ import annotations

from typing import Any, Iterable

from app.travel.constraints import TripConstraints
from app.travel.daily_planning import DailyPlanner
from app.travel.mobility import MobilityProfile
from app.travel.routing import RoutingService
from app.travel.trip_strategy import TripStrategy


MAX_ROUTED_REGIONAL_ANCHORS = 8
MAX_ROUTED_COMPANIONS_PER_ANCHOR = 6


def direct_km(first: dict[str, Any], second: dict[str, Any]) -> float | None:
    try:
        return DailyPlanner._distance_km(float(first["latitude"]), float(first["longitude"]), float(second["latitude"]), float(second["longitude"]))
    except (KeyError, TypeError, ValueError):
        return None


def regional_mode(profile: MobilityProfile) -> tuple[str, float, float] | None:
    """ORS-supported mode and conservative direct-distance discovery band."""
    if profile.preferred_transport == "motorcycle":
        return "car", 8.0, 35.0  # Car-road proxy, never motorcycle verification.
    car_available = (profile.own_car is True or profile.rental_car_allowed is True) and profile.driving_license is not False
    if car_available and (profile.preferred_transport == "car" or profile.mixed_strategy and profile.allows("car")):
        return "car", 8.0, 35.0
    if profile.preferred_transport == "bicycle" or profile.mixed_strategy and profile.allows("bicycle"):
        return "bicycle", 4.0, 14.0
    # ORS does not supply a public-transport profile. Never certify a transit
    # day trip using a car or walking route as a substitute.
    return None


def promote_regional_day(
    itinerary: list[dict[str, Any]], ranked_places: Iterable[Any],
    accommodation: dict[str, Any] | None, profile: MobilityProfile,
    constraints: TripConstraints, strategy: TripStrategy, routing: RoutingService,
    *, excluded_names: set[str] | None = None,
) -> bool:
    """Replace one weak day with a coherent, routed regional pair when feasible.

    The daily planner remains the schedule authority. This pass only selects
    provider-backed places whose road/cycle legs are verified and reasonably
    fit the explicit travel cap and conservative activity workload.
    """
    mode_band = regional_mode(profile)
    days = [day for day in itinerary if isinstance(day, dict)]
    if mode_band is None or len(days) < 2 or not isinstance(accommodation, dict):
        return False
    mode, minimum_km, maximum_km = mode_band
    ranked = [item for item in ranked_places if isinstance(getattr(item, "place", None), dict)]
    by_name = {str(item.place.get("name", "")).casefold(): item for item in ranked}
    selected_names = {str(activity.get("name", "")).casefold() for day in days for activity in day.get("activities", []) if isinstance(activity, dict)}
    selected_anchor_days = {
        str(day["activities"][0].get("name", "")).casefold(): day
        for day in days[1:] if isinstance(day.get("activities"), list) and len(day["activities"]) == 1
        and isinstance(day["activities"][0], dict)
    }
    excluded = {name.casefold() for name in excluded_names or set()}
    strong = set(strategy.primary_concepts[:3])
    no_more_than = constraints.preferred_activity_count or (1 if strategy.pace == "relaxed" else 2)
    if no_more_than < 2:
        return False
    max_travel = min(constraints.max_daily_travel_minutes or 180, 210)

    def verified_route(first: dict[str, Any], last: dict[str, Any]):
        route = routing.route(first, last, mode)
        return route if route.data_status == "verified" and route.duration_minutes is not None and route.distance_meters is not None else None

    # First try to complete a selected regional stop, then introduce an unused
    # anchor if the model selected only local places.
    selected_regional_candidates = []
    unused_regional_candidates = []
    for item in ranked:
        distance = direct_km(accommodation, item.place)
        name = str(item.place.get("name", ""))
        if (name and name.casefold() not in excluded and not item.has_strong_negative_conflict
                and distance is not None and minimum_km <= distance <= maximum_km
                and (not strong or strong.intersection(item.matched_concepts))):
            if name.casefold() in selected_anchor_days:
                selected_regional_candidates.append(item)
            elif name.casefold() not in selected_names:
                unused_regional_candidates.append(item)
    regional_candidates = selected_regional_candidates + unused_regional_candidates
    for anchor in regional_candidates[:MAX_ROUTED_REGIONAL_ANCHORS]:
        place = anchor.place
        name = str(place.get("name", ""))
        outward = verified_route(accommodation, place)
        if outward is None or outward.duration_minutes >= max_travel:
            continue
        partner_choices = []
        potential_companions = []
        for candidate in ranked:
            other = candidate.place
            other_name = str(other.get("name", ""))
            separation = direct_km(place, other)
            if (not other_name or other_name.casefold() in selected_names | excluded
                    or other_name.casefold() == name.casefold() or candidate.has_strong_negative_conflict
                    or separation is None or separation > 4):
                continue
            potential_companions.append(candidate)
        for candidate in potential_companions[:MAX_ROUTED_COMPANIONS_PER_ANCHOR]:
            other = candidate.place
            middle = verified_route(place, other)
            returning = verified_route(other, accommodation)
            if middle is None or returning is None:
                continue
            travel_minutes = outward.duration_minutes + middle.duration_minutes + returning.duration_minutes
            if travel_minutes > max_travel:
                continue
            visit_minutes = DailyPlanner._duration_for(place)[0] + DailyPlanner._duration_for(other)[0]
            if travel_minutes + visit_minutes + (constraints.meal_duration_minutes or 60) > 450:
                continue
            partner_choices.append((candidate, travel_minutes, outward, middle, returning))
        if not partner_choices:
            continue
        partner, travel_minutes, outward, middle, returning = min(
            partner_choices,
            key=lambda value: (-len(strong.intersection(value[0].matched_concepts)), -value[0].final_score, value[1]),
        )
        # Keep one local day intact. Replacing the least preference-supported
        # later day avoids displacing a strong match merely for distance.
        def day_priority(day: dict[str, Any]) -> tuple[int, int]:
            activities = [activity for activity in day.get("activities", []) if isinstance(activity, dict)]
            evidence = sum(len(strong.intersection(by_name[str(activity.get("name", "")).casefold()].matched_concepts)) for activity in activities if str(activity.get("name", "")).casefold() in by_name)
            return evidence, len(activities)
        chosen = selected_anchor_days.get(name.casefold()) or min(days[1:], key=day_priority)
        chosen["activities"] = [
            {"name": name, "address": str(place.get("address", "")), "reason": ""},
            {"name": partner.place["name"], "address": str(partner.place.get("address", "")), "reason": ""},
        ]
        chosen["regional_trip"] = {
            "status": "verified car-road proxy" if profile.preferred_transport == "motorcycle" else "verified",
            "transport_mode": profile.preferred_transport if profile.preferred_transport == "motorcycle" else mode,
            "anchor": name, "companion": partner.place["name"],
            "distance_from_accommodation_meters": outward.distance_meters,
            "round_trip_distance_meters": sum(route.distance_meters for route in (outward, middle, returning)),
            "round_trip_duration_minutes": travel_minutes if profile.preferred_transport != "motorcycle" else None,
            "source": "OpenRouteService", "place_source": "Geoapify",
        }
        return True
    return False


def fill_sparse_days(
    itinerary: list[dict[str, Any]], ranked_places: Iterable[Any],
    constraints: TripConstraints, strategy: TripStrategy, routing: RoutingService,
    profile: MobilityProfile,
) -> int:
    """Add one nearby, preference-ranked afternoon stop to under-filled days.

    This is a candidate-selection pass, not a fixed activity count: relaxed or
    time-constrained days remain slow, and DailyPlanner may still reject a stop
    that does not fit the actual schedule.
    """
    if (strategy.pace == "relaxed" or constraints.preferred_activity_count == 1
            or (constraints.min_daily_free_minutes or 0) >= 240):
        return 0
    ranked = [item for item in ranked_places if isinstance(getattr(item, "place", None), dict)]
    by_name = {str(item.place.get("name", "")).casefold(): item.place for item in ranked}
    used = {str(activity.get("name", "")).casefold() for day in itinerary if isinstance(day, dict) for activity in day.get("activities", []) if isinstance(activity, dict)}
    mode = profile.planning_mode()
    if mode not in {"walking", "car", "bicycle"}:
        mode = "walking"
    added = 0
    for day in itinerary:
        if not isinstance(day, dict) or len(day.get("activities", [])) != 1:
            continue
        current = day["activities"][0]
        anchor = by_name.get(str(current.get("name", "")).casefold()) if isinstance(current, dict) else None
        if not isinstance(anchor, dict):
            continue
        for item in ranked:
            place = item.place
            name = str(place.get("name", ""))
            separation = direct_km(anchor, place)
            if (not name or name.casefold() in used or item.has_strong_negative_conflict
                    or separation is None or separation > 3):
                continue
            if DailyPlanner._duration_for(anchor)[0] + DailyPlanner._duration_for(place)[0] > 300:
                continue
            route = routing.route(anchor, place, mode)
            if route.data_status == "verified" and route.duration_minutes is not None:
                if route.duration_minutes > 45:
                    continue
            elif separation > 1.5:
                # Unverified transfer is acceptable only for a genuinely local
                # companion and remains an estimated planning buffer later.
                continue
            day["activities"].append({"name": name, "address": str(place.get("address", "")), "reason": ""})
            used.add(name.casefold())
            added += 1
            break
    return added


def keep_selected_places_mobility_compatible(
    itinerary: list[dict[str, Any]], ranked_places: Iterable[Any],
    accommodation: dict[str, Any] | None, profile: MobilityProfile,
) -> int:
    """Swap demonstrably distant stops for local verified options when needed.

    Public-transport reachability is not verified by ORS, so the conservative
    local band is a selection heuristic, never a claim of a verified transit
    route. The same rule works for arbitrary intent concepts.
    """
    if not isinstance(accommodation, dict):
        return 0
    mode = profile.planning_mode()
    limit = 5.0 if profile.walking_only or mode == "walking" else 6.0 if mode == "public_transport" else 14.0 if mode == "bicycle" else None
    if limit is None:
        return 0
    ranked = [item for item in ranked_places if isinstance(getattr(item, "place", None), dict)]
    by_name = {str(item.place.get("name", "")).casefold(): item for item in ranked}
    used = {str(activity.get("name", "")).casefold() for day in itinerary if isinstance(day, dict) for activity in day.get("activities", []) if isinstance(activity, dict)}
    replaced = 0
    for day in itinerary:
        if not isinstance(day, dict):
            continue
        for activity in day.get("activities", []):
            if not isinstance(activity, dict):
                continue
            name = str(activity.get("name", ""))
            original = by_name.get(name.casefold())
            if original is None:
                continue
            distance = direct_km(accommodation, original.place)
            if distance is None or distance <= limit:
                continue
            alternatives = [item for item in ranked if not item.has_strong_negative_conflict
                            and str(item.place.get("name", "")).casefold() not in used
                            and (local_distance := direct_km(accommodation, item.place)) is not None
                            and local_distance <= limit]
            if not alternatives:
                day["mobility_warning"] = "No verified local alternative was available; this stop's practical reachability is unverified."
                continue
            replacement = min(alternatives, key=lambda item: (-len(set(original.matched_concepts).intersection(item.matched_concepts)), -item.final_score, direct_km(accommodation, item.place) or 0))
            used.discard(name.casefold())
            used.add(str(replacement.place["name"]).casefold())
            activity.update({"name": replacement.place["name"], "address": str(replacement.place.get("address", "")), "reason": ""})
            replaced += 1
    return replaced


def refresh_regional_explanations(plan: dict[str, Any]) -> None:
    """Remove stale regional claims after editing; use current stored route legs."""
    hotel = plan.get("selected_accommodation")
    if not isinstance(hotel, dict):
        return
    for day in plan.get("itinerary", []):
        if not isinstance(day, dict):
            continue
        regional = day.get("regional_trip")
        if not isinstance(regional, dict):
            continue
        if len(day.get("activities", [])) != 2:
            day.pop("regional_trip", None)
            continue
        names = {str(item.get("name", "")) for item in day.get("activities", []) if isinstance(item, dict)}
        if regional.get("anchor") not in names or regional.get("companion") not in names:
            day.pop("regional_trip", None)
            continue
        activities = day.get("activities", [])
        first = next((item for item in activities if isinstance(item, dict) and item.get("name") == regional["anchor"]), None)
        second = next((item for item in activities if isinstance(item, dict) and item.get("name") == regional["companion"]), None)
        route = first.get("route") if isinstance(first, dict) else None
        middle = second.get("route") if isinstance(second, dict) else None
        returning = day.get("return_route")
        legs = (route, middle, returning)
        if (not isinstance(route, dict) or route.get("origin", {}).get("name") != hotel.get("name")
                or not isinstance(middle, dict) or middle.get("origin", {}).get("name") != regional["anchor"]
                or not isinstance(returning, dict) or returning.get("destination", {}).get("name") != hotel.get("name")
                or any(not isinstance(leg, dict) or leg.get("data_status") != "verified" or not isinstance(leg.get("distance_meters"), (int, float)) for leg in legs)):
            day.pop("regional_trip", None)
            continue
        regional["distance_from_accommodation_meters"] = route.get("distance_meters")
        regional["round_trip_distance_meters"] = sum(float(leg["distance_meters"]) for leg in legs)
        regional["round_trip_duration_minutes"] = sum(int(leg["duration_minutes"]) for leg in legs) if regional.get("transport_mode") != "motorcycle" and all(isinstance(leg.get("duration_minutes"), int) for leg in legs) else None
