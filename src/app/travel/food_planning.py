"""Real Geoapify-backed meal choices for an already validated activity plan."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any, Iterable

from app.ai.intent_analyzer import IntentPreference
from app.travel.itinerary import place_snapshot
from app.travel.mobility import MobilityProfile
from app.travel.place_ranking import rank_places
from app.travel.routing import RoutingService, UnavailableRoutingService
from app.travel.budget import TripBudget, prefer_affordable


class FoodPlanner:
    """Attach several factual food options without selecting or inventing one."""

    def __init__(self, routing_service: RoutingService | None = None) -> None:
        self.routing_service = routing_service or UnavailableRoutingService()

    def attach_options(
        self,
        itinerary: list[dict[str, Any]],
        food_places: Iterable[dict[str, Any]],
        intents: Iterable[IntentPreference],
        mobility_profile: MobilityProfile | None,
        accommodation: dict[str, Any] | None,
        *,
        limit: int = 3,
        budget: TripBudget | None = None,
    ) -> None:
        ranked = rank_places(food_places, intents, mobility_profile)
        candidates = prefer_affordable(
            [item.place for item in ranked if self._is_food_place(item.place)], budget or TripBudget()
        )
        used: set[str] = set()
        for day in itinerary:
            if not isinstance(day, dict):
                continue
            activities = [item for item in day.get("activities", []) if isinstance(item, dict)]
            if not activities:
                continue
            lunch_anchor = activities[0]
            dinner_anchor = activities[-1] if activities else accommodation
            meals = day.get("meals", [])
            if not isinstance(meals, list):
                continue
            for meal in meals:
                if not isinstance(meal, dict):
                    continue
                anchor = lunch_anchor if meal.get("meal_type") == "lunch" else (dinner_anchor or accommodation)
                options = self._nearby_options(candidates, anchor, mobility_profile, used, limit)
                # The first pass avoids repetition across the whole itinerary.
                # If the finite city pool is exhausted, retain factual food choices
                # rather than reporting unavailable food where real options exist.
                if not options and candidates:
                    options = self._nearby_options(candidates, anchor, mobility_profile, set(), limit)
                meal["anchor"] = place_snapshot(anchor)
                meal["options"] = options
                meal["options_status"] = "verified" if options else "unavailable"
                meal["source"] = "Geoapify" if options else None
                self._insert_options_into_timeline(day, meal)

    def _nearby_options(
        self,
        candidates: list[dict[str, Any]],
        anchor: dict[str, Any] | None,
        mobility_profile: MobilityProfile | None,
        used: set[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not isinstance(anchor, dict):
            return []
        mode = mobility_profile.planning_mode() if mobility_profile else "walking"
        if mode not in {"walking", "car", "driving", "bicycle"}:
            mode = "walking"
        options: list[tuple[tuple[int, float, float, str], dict[str, Any]]] = []
        for preference_rank, candidate in enumerate(candidates):
            name = candidate.get("name")
            key = name.casefold() if isinstance(name, str) else ""
            if not key or key in used:
                continue
            route = self.routing_service.route(anchor, candidate, mode)
            direct_distance = self._straight_distance(anchor, candidate)
            option = place_snapshot(candidate)
            option.update({
                "route_from_anchor": route.to_dict(),
                "travel_distance_meters": route.distance_meters if route.data_status == "verified" else None,
                "travel_duration_minutes": route.duration_minutes if route.data_status == "verified" else None,
                "travel_time_data_status": route.data_status,
                "transport_mode": route.transport_mode,
                "source": "Geoapify",
            })
            route_order = route.duration_minutes if route.data_status == "verified" and route.duration_minutes is not None else 10_000
            distance_order = direct_distance if direct_distance is not None else float("inf")
            # Food intent ranking remains meaningful while routing breaks ties
            # among similarly relevant provider places.  This avoids choosing
            # the nearest unrelated café over a verified local-food match.
            options.append(((preference_rank, route_order, distance_order, key), option))
        options.sort(key=lambda item: item[0])
        selected = [item for _, item in options[:limit]]
        used.update(str(item["name"]).casefold() for item in selected)
        return selected

    @staticmethod
    def _is_food_place(place: dict[str, Any]) -> bool:
        categories = " ".join(str(value).casefold() for value in place.get("categories", []))
        return any(term in categories for term in ("catering.restaurant", "catering.cafe", "catering.food_court", "commercial.marketplace"))

    @staticmethod
    def _straight_distance(origin: dict[str, Any], destination: dict[str, Any]) -> float | None:
        try:
            lat1, lon1 = float(origin["latitude"]), float(origin["longitude"])
            lat2, lon2 = float(destination["latitude"]), float(destination["longitude"])
        except (KeyError, TypeError, ValueError):
            return None
        radius = 6_371_000
        d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
        a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
        return 2 * radius * asin(sqrt(a))

    @staticmethod
    def _insert_options_into_timeline(day: dict[str, Any], meal: dict[str, Any]) -> None:
        for item in day.get("items", []):
            if isinstance(item, dict) and item.get("item_type") == "meal" and item.get("meal_type") == meal.get("meal_type"):
                item["options"] = meal.get("options", [])
                item["options_status"] = meal.get("options_status")
                item["anchor"] = meal.get("anchor")
