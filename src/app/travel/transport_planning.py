"""Journey and fuel calculations from provider routes and explicit user inputs."""

from __future__ import annotations

from math import isfinite
from typing import Any, Callable

import requests

from app.travel.geocoding import get_coordinates
from app.travel.routing import RoutingService


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number > 0 else None


def fuel_cost(distance_meters: object, consumption: object, fuel_price: object) -> float | None:
    """Calculate an estimate only when all three inputs have known provenance."""
    distance = _positive_number(distance_meters)
    litres_per_100km = _positive_number(consumption)
    eur_per_litre = _positive_number(fuel_price)
    if None in (distance, litres_per_100km, eur_per_litre):
        return None
    return round(distance / 1000 * litres_per_100km / 100 * eur_per_litre, 2)


def build_journey(
    preferences: dict[str, Any], destination: dict[str, Any],
    accommodation: dict[str, Any] | None, routing: RoutingService,
    *, geocode: Callable[[str, str], dict[str, Any]] = get_coordinates,
    origin_place: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan the round trip; unknown provider facts remain explicitly unknown."""
    origin_text = str(preferences.get("origin") or "").strip()
    selected_mode = str(preferences.get("destination_transport") or "").strip()
    mode = selected_mode.casefold() if selected_mode in {"Car", "Motorcycle", "Plane", "Train", "Bus"} else None
    destination_name = ", ".join(str(destination.get(key)) for key in ("city", "country") if destination.get(key))
    consumption = _positive_number(preferences.get("fuel_consumption_l_per_100km"))
    fuel_price = _positive_number(preferences.get("fuel_price_eur_per_litre"))
    result: dict[str, Any] = {
        "origin": origin_text or None, "destination": destination_name or None,
        "origin_place": None,
        "requested_mode": selected_mode or None,
        "journey_vehicle": preferences.get("journey_vehicle") if mode in {"car", "motorcycle"} else None,
        "fuel_consumption_l_per_100km": consumption,
        "fuel_price_eur_per_litre": fuel_price,
        "outbound": {"route": None, "distance_meters": None, "duration_minutes": None, "fuel_cost_eur": None, "status": "unavailable"},
        "return": {"route": None, "distance_meters": None, "duration_minutes": None, "fuel_cost_eur": None, "status": "unavailable"},
        "note": "Intercity fares and fuel prices are unavailable from the approved providers.",
    }
    if not origin_text or mode not in {"car", "motorcycle"} or not isinstance(accommodation, dict):
        return result
    try:
        origin = origin_place if isinstance(origin_place, dict) else geocode(origin_text, "")
    except (OSError, ValueError, TypeError, KeyError, requests.RequestException):
        return result
    if not isinstance(origin, dict):
        return result
    result["origin_place"] = origin
    # ORS offers a car road profile, not motorcycle-specific legal access.
    # Motorcycle uses the verified road distance as a labelled proxy only.
    for key, first, last in (("outbound", origin, accommodation), ("return", accommodation, origin)):
        route = routing.route(first, last, "car")
        if route.data_status != "verified" or route.distance_meters is None:
            continue
        result[key] = {
            "route": route.to_dict(), "distance_meters": route.distance_meters,
            "duration_minutes": route.duration_minutes if mode == "car" else None,
            "fuel_cost_eur": fuel_cost(route.distance_meters, consumption, fuel_price),
            "status": "verified car route" if mode == "car" else "verified car-road distance; motorcycle suitability unavailable",
        }
    result["note"] = (
        "Fuel cost is calculated from ORS road distance and user-supplied consumption and fuel price; other vehicle costs remain unknown."
        if consumption and fuel_price else
        "ORS road distance may be available; fuel cost needs user-supplied consumption and fuel price."
    )
    return result


def local_fuel_cost(plan: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    """Calculate only the recorded local driving legs, never a whole-day fare."""
    mobility = plan.get("mobility_profile", {})
    if not isinstance(mobility, dict):
        return {"cost_eur": None, "distance_meters": None, "status": "unavailable"}
    legs = [
        item for day in plan.get("itinerary", []) if isinstance(day, dict)
        for item in day.get("items", []) if isinstance(item, dict) and item.get("item_type") == "travel"
    ]
    verified = [item for item in legs if item.get("transport_mode") == "car" and item.get("travel_time_data_status") == "verified" and _positive_number(item.get("travel_distance_meters"))]
    return_routes = [
        day["return_route"] for day in plan.get("itinerary", []) if isinstance(day, dict)
        and isinstance(day.get("return_route"), dict)
        and day["return_route"].get("transport_mode") == "car"
        and day["return_route"].get("data_status") == "verified"
        and _positive_number(day["return_route"].get("distance_meters"))
    ]
    if not verified and not return_routes:
        return {"cost_eur": None, "distance_meters": None, "status": "unavailable"}
    distance = sum(float(item["travel_distance_meters"]) for item in verified) + sum(float(route["distance_meters"]) for route in return_routes)
    cost = fuel_cost(distance, preferences.get("fuel_consumption_l_per_100km"), preferences.get("fuel_price_eur_per_litre"))
    return {
        "cost_eur": cost, "distance_meters": distance,
        "status": "partial calculated fuel estimate" if cost is not None else "partial verified distance; fuel inputs unavailable",
    }
