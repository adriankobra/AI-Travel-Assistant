"""Checks that UI, map and PDF all describe one validated plan snapshot."""

from __future__ import annotations

from typing import Any


class PlanConsistencyError(ValueError):
    """Raised when derived itinerary data belongs to an older plan."""


def validate_plan_consistency(plan: dict[str, Any]) -> None:
    """Reject stale derived fields before a plan is stored or exported.

    The map and PDF are rendered from ``itinerary``.  Ensuring that its route
    stops and timeline activities match the current accommodation/activity
    snapshots prevents a hotel replacement from retaining an old map route.
    """
    hotel = plan.get("selected_accommodation")
    hotel_name = hotel.get("name") if isinstance(hotel, dict) else None
    if not isinstance(hotel_name, str) or not hotel_name:
        raise PlanConsistencyError("The current plan has no verified accommodation.")
    for day in plan.get("itinerary", []):
        if not isinstance(day, dict):
            raise PlanConsistencyError("The current plan contains an invalid day.")
        activity_names = {
            item.get("name") for item in day.get("activities", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        stops = day.get("route_stops", [])
        if stops:
            names = [item.get("name") for item in stops if isinstance(item, dict)]
            if names[0] != hotel_name or names[-1] != hotel_name:
                raise PlanConsistencyError("A day route does not use the current accommodation as its base.")
            if not activity_names.issubset(set(names)):
                raise PlanConsistencyError("A day route contains stale or missing activity stops.")
        timeline_names = {
            item.get("name") for item in day.get("items", [])
            if isinstance(item, dict) and item.get("item_type") == "activity"
        }
        if timeline_names != activity_names:
            raise PlanConsistencyError("The timeline and activities do not describe the same plan.")
        regional = day.get("regional_trip")
        if isinstance(regional, dict) and {regional.get("anchor"), regional.get("companion")} - activity_names:
            raise PlanConsistencyError("A regional-day explanation refers to a removed activity.")
        if isinstance(regional, dict):
            activities = day.get("activities", [])
            if len(activities) < 2 or activities[0].get("name") != regional.get("anchor") or activities[1].get("name") != regional.get("companion"):
                raise PlanConsistencyError("The regional-day explanation is out of itinerary order.")
            legs = [activities[0].get("route"), activities[1].get("route"), day.get("return_route")]
            if any(not isinstance(leg, dict) or leg.get("data_status") != "verified" or not isinstance(leg.get("distance_meters"), (int, float)) for leg in legs):
                raise PlanConsistencyError("The regional-day explanation lacks verified route legs.")
            actual_distance = sum(float(leg["distance_meters"]) for leg in legs)
            if not isinstance(regional.get("round_trip_distance_meters"), (int, float)) or abs(actual_distance - regional["round_trip_distance_meters"]) > 1:
                raise PlanConsistencyError("The regional-day distance is stale.")
        returning = day.get("return_route")
        if isinstance(returning, dict) and returning.get("data_status") == "verified":
            destination = returning.get("destination")
            origin = returning.get("origin")
            last_name = day.get("activities", [])[-1].get("name") if day.get("activities") and isinstance(day["activities"][-1], dict) else None
            if not isinstance(destination, dict) or destination.get("name") != hotel_name or not isinstance(origin, dict) or origin.get("name") != last_name:
                raise PlanConsistencyError("The return route does not match the current hotel and activities.")
