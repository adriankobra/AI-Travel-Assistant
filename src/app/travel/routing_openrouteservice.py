"""OpenRouteService implementation of the provider-neutral routing contract."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from app.travel.routing import RouteEstimate


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ORS_DIRECTIONS_URL = "https://api.heigit.org/openrouteservice/v2/directions"
ORS_PROFILES = {
    "walking": "foot-walking",
    "driving": "driving-car",
    "car": "driving-car",  # Existing MobilityProfile terminology.
    "bicycle": "cycling-regular",
}


class OpenRouteServiceRoutingService:
    """Fetch verified route summaries from ORS and safely degrade on failure.

    This class deliberately returns an unavailable ``RouteEstimate`` for every
    provider, configuration, or data problem.  Planning can then retain its
    explicitly labelled conservative transition buffer without fabricating a
    route result.
    """

    source = "openrouteservice"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        session: requests.Session | Any | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
        self._api_key = api_key if api_key is not None else os.getenv("ORS_API_KEY")
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds
        self._cache: dict[tuple[float, float, float, float, str], RouteEstimate] = {}

    def route(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        transport_mode: str | None,
    ) -> RouteEstimate:
        profile = ORS_PROFILES.get(transport_mode or "")
        coordinates = self._coordinates(origin), self._coordinates(destination)
        if not self._api_key or not profile or None in coordinates:
            return self._unavailable(origin, destination, transport_mode)

        start, end = coordinates
        assert start is not None and end is not None  # Narrowed by the guard above.
        cache_key = (*start, *end, transport_mode or "")
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            response = self._session.post(
                f"{ORS_DIRECTIONS_URL}/{profile}/json",
                headers={"Authorization": self._api_key, "Content-Type": "application/json"},
                json={"coordinates": [[start[1], start[0]], [end[1], end[0]]]},
                timeout=self._timeout_seconds,
            )
            if getattr(response, "status_code", None) != 200:
                result = self._unavailable(origin, destination, transport_mode)
            else:
                result = self._from_response(response.json(), origin, destination, transport_mode)
        except Exception:
            # A provider failure must never make itinerary generation fail.  The
            # returned record intentionally contains no invented route values.
            result = self._unavailable(origin, destination, transport_mode)

        self._cache[cache_key] = result
        return result

    @staticmethod
    def _coordinates(place: dict[str, Any]) -> tuple[float, float] | None:
        if not isinstance(place, dict):
            return None
        try:
            latitude = float(place["latitude"])
            longitude = float(place["longitude"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            return None
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
        return latitude, longitude

    def _from_response(
        self,
        payload: Any,
        origin: dict[str, Any],
        destination: dict[str, Any],
        transport_mode: str | None,
    ) -> RouteEstimate:
        try:
            summary = payload["routes"][0]["summary"]
            distance = float(summary["distance"])
            duration_seconds = float(summary["duration"])
        except (KeyError, TypeError, ValueError, IndexError):
            return self._unavailable(origin, destination, transport_mode)
        if not (math.isfinite(distance) and math.isfinite(duration_seconds)):
            return self._unavailable(origin, destination, transport_mode)
        if distance < 0 or duration_seconds < 0:
            return self._unavailable(origin, destination, transport_mode)
        return RouteEstimate(
            origin=origin,
            destination=destination,
            transport_mode=transport_mode,
            distance_meters=distance,
            duration_minutes=round(duration_seconds / 60),
            status="success",
            source=self.source,
            data_status="verified",
        )

    @staticmethod
    def _unavailable(
        origin: dict[str, Any], destination: dict[str, Any], transport_mode: str | None
    ) -> RouteEstimate:
        return RouteEstimate(origin, destination, transport_mode, None, None, "unavailable", None, "unavailable")
