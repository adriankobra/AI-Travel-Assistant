"""Coordinate-first external map links; no Google Maps API is used."""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import urlencode


GOOGLE_MAPS_SEARCH_URL = "https://www.google.com/maps/search/?"
GOOGLE_MAPS_DIRECTIONS_URL = "https://www.google.com/maps/dir/?"
MAX_DIRECTIONS_WAYPOINTS = 9


def _coordinate_query(place: dict[str, Any]) -> str | None:
    try:
        latitude, longitude = float(place["latitude"]), float(place["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return f"{latitude:.6f},{longitude:.6f}"


def build_location_map_url(place: dict[str, Any]) -> str | None:
    """Build a public Google Maps search URL using verified place identity first."""
    name = str(place.get("name", "")).strip()
    address = str(place.get("address", "")).strip()
    city = str(place.get("city", "")).strip()
    country = str(place.get("country", "")).strip()
    # Geoapify addresses frequently start with the place name.  Do not repeat
    # it in Google Maps' query: name + street/city/country is both clearer and
    # a more reliable search signal than "Name, Name, Street ...".
    address_without_name = address
    if name and address.casefold().startswith(name.casefold()):
        address_without_name = address[len(name):].lstrip(" ,")
    query = ", ".join(dict.fromkeys(value for value in (name, address_without_name, city, country) if value))
    if not query:
        query = _coordinate_query(place)
    if not query:
        return None
    return GOOGLE_MAPS_SEARCH_URL + urlencode({"api": "1", "query": query})


def build_route_map_url(origin: dict[str, Any], destination: dict[str, Any], transport_mode: str | None = None) -> str | None:
    """Build an external route link only when both endpoints are coordinate-backed."""
    origin_query, destination_query = _coordinate_query(origin), _coordinate_query(destination)
    if origin_query is None or destination_query is None:
        return None
    params = {"api": "1", "origin": origin_query, "destination": destination_query}
    if transport_mode in {"walking", "driving", "bicycle"}:
        params["travelmode"] = {"bicycle": "bicycling"}.get(transport_mode, transport_mode)
    return GOOGLE_MAPS_DIRECTIONS_URL + urlencode(params)


def build_multi_stop_map_url(stops: Iterable[dict[str, Any]], transport_mode: str | None = None) -> str | None:
    """Build one daily route link when Google Maps' waypoint limit is respected.

    The helper deliberately returns ``None`` for an incomplete or overlong route
    so the UI can fall back to individual location links instead of silently
    dropping destinations.
    """
    coordinates = [_coordinate_query(place) for place in stops]
    if len(coordinates) < 2 or any(value is None for value in coordinates):
        return None
    assert all(value is not None for value in coordinates)
    waypoints = coordinates[1:-1]
    if len(waypoints) > MAX_DIRECTIONS_WAYPOINTS:
        return None
    params = {"api": "1", "origin": coordinates[0], "destination": coordinates[-1]}
    if waypoints:
        params["waypoints"] = "|".join(waypoints)
    if transport_mode in {"walking", "driving", "bicycle"}:
        params["travelmode"] = {"bicycle": "bicycling"}.get(transport_mode, transport_mode)
    return GOOGLE_MAPS_DIRECTIONS_URL + urlencode(params)
