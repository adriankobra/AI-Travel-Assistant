"""Offline tests for the isolated OpenRouteService routing provider."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

import requests


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.travel.daily_planning import DailyPlanner
from app.travel.mobility import MobilityProfile
from app.travel.routing import RouteEstimate, UnavailableRoutingService
from app.travel.routing_openrouteservice import OpenRouteServiceRoutingService


def place(name: str, latitude: float = 56.95, longitude: float = 24.10) -> dict:
    return {"name": name, "address": f"{name} address", "categories": ["tourism.sights"], "latitude": latitude, "longitude": longitude}


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"routes": [{"summary": {"distance": 1234.5, "duration": 900}}]}

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class VerifiedRoutingService:
    def route(self, origin: dict, destination: dict, transport_mode: str | None) -> RouteEstimate:
        return RouteEstimate(origin, destination, transport_mode, 820, 12, "success", "openrouteservice", "verified")


class RecordingRoutingService:
    def __init__(self) -> None:
        self.modes: list[str | None] = []

    def route(self, origin: dict, destination: dict, transport_mode: str | None) -> RouteEstimate:
        self.modes.append(transport_mode)
        return RouteEstimate(origin, destination, transport_mode, None, None, "unavailable", None, "unavailable")


class OpenRouteServiceRoutingTests(unittest.TestCase):
    def _service(self, response: FakeResponse | Exception = FakeResponse(), api_key: str | None = "test-key") -> tuple[OpenRouteServiceRoutingService, FakeSession]:
        session = FakeSession(response)
        return OpenRouteServiceRoutingService(api_key, session=session), session

    def test_successful_walking_route_maps_verified_summary(self) -> None:
        service, session = self._service()
        route = service.route(place("Origin"), place("Destination", 56.96, 24.11), "walking")
        self.assertEqual(route.status, "success")
        self.assertEqual(route.source, "openrouteservice")
        self.assertEqual(route.data_status, "verified")
        self.assertEqual(route.transport_mode, "walking")
        self.assertEqual(route.distance_meters, 1234.5)
        self.assertEqual(route.duration_minutes, 15)
        self.assertTrue(session.calls[0]["url"].endswith("/foot-walking/json"))
        self.assertEqual(session.calls[0]["json"], {"coordinates": [[24.1, 56.95], [24.11, 56.96]]})

    def test_driving_and_existing_car_alias_use_driving_car_profile(self) -> None:
        for mode in ("driving", "car"):
            service, session = self._service()
            route = service.route(place("A"), place("B", 56.96, 24.11), mode)
            self.assertEqual(route.transport_mode, mode)
            self.assertTrue(session.calls[0]["url"].endswith("/driving-car/json"))

    def test_bicycle_uses_cycling_regular_profile(self) -> None:
        service, session = self._service()
        route = service.route(place("A"), place("B", 56.96, 24.11), "bicycle")
        self.assertEqual(route.status, "success")
        self.assertTrue(session.calls[0]["url"].endswith("/cycling-regular/json"))

    def test_public_transport_and_unsupported_modes_are_unavailable_without_request(self) -> None:
        for mode in ("public_transport", "motorcycle", None):
            service, session = self._service()
            route = service.route(place("A"), place("B"), mode)
            self.assertEqual(route.status, "unavailable")
            self.assertEqual(route.data_status, "unavailable")
            self.assertEqual(session.calls, [])

    def test_missing_key_and_invalid_coordinates_are_unavailable(self) -> None:
        service, session = self._service(api_key="")
        self.assertEqual(service.route(place("A"), place("B"), "walking").status, "unavailable")
        self.assertEqual(session.calls, [])
        service, session = self._service()
        self.assertEqual(service.route({"name": "A"}, place("B"), "walking").status, "unavailable")
        self.assertEqual(service.route(place("A", 100, 24.1), place("B"), "walking").status, "unavailable")
        self.assertEqual(session.calls, [])

    def test_provider_errors_network_errors_and_malformed_responses_are_unavailable(self) -> None:
        for response in (FakeResponse(401), FakeResponse(429), requests.ConnectionError("offline"), FakeResponse(payload={"routes": []})):
            service, _ = self._service(response)
            route = service.route(place("A"), place("B", 56.96, 24.11), "walking")
            self.assertEqual(route.status, "unavailable")
            self.assertIsNone(route.distance_meters)
            self.assertIsNone(route.duration_minutes)

    def test_duplicate_route_requests_are_cached(self) -> None:
        service, session = self._service()
        origin, destination = place("A"), place("B", 56.96, 24.11)
        first = service.route(origin, destination, "walking")
        second = service.route(origin, destination, "walking")
        self.assertEqual(first, second)
        self.assertEqual(len(session.calls), 1)

    def test_daily_planner_uses_verified_route_duration(self) -> None:
        itinerary = [{"day": 1, "activities": [{"name": "A", "address": "", "reason": ""}, {"name": "B", "address": "", "reason": ""}]}]
        DailyPlanner(VerifiedRoutingService()).plan(itinerary, [place("A"), place("B", 56.96, 24.11)], [], {}, {}, MobilityProfile(preferred_transport="walking"))
        second = itinerary[0]["activities"][1]
        self.assertEqual(second["transition_buffer_minutes_before"], 12)
        self.assertEqual(second["transition_buffer_status"], "verified")
        self.assertEqual(second["travel_time_minutes"], 12)
        self.assertEqual(second["travel_time_data_status"], "verified")
        self.assertEqual(second["route"]["source"], "openrouteservice")

    def test_daily_planner_keeps_estimated_buffer_when_route_is_unavailable(self) -> None:
        itinerary = [{"day": 1, "activities": [{"name": "A", "address": "", "reason": ""}, {"name": "B", "address": "", "reason": ""}]}]
        DailyPlanner(UnavailableRoutingService()).plan(itinerary, [place("A"), place("B", 56.96, 24.11)], [], {}, {}, MobilityProfile(preferred_transport="walking"))
        second = itinerary[0]["activities"][1]
        self.assertEqual(second["transition_buffer_status"], "estimated")
        self.assertEqual(second["travel_time_data_status"], "unavailable")
        self.assertNotEqual(second["route"]["data_status"], "verified")

    def test_walking_only_profile_never_uses_driving(self) -> None:
        routing = RecordingRoutingService()
        itinerary = [{"day": 1, "activities": [{"name": "A", "address": "", "reason": ""}, {"name": "B", "address": "", "reason": ""}]}]
        profile = MobilityProfile(allowed_transport_modes=("walking",), preferred_transport="walking", car_usage=False)
        DailyPlanner(routing).plan(itinerary, [place("A"), place("B", 56.96, 24.11)], [], {}, {}, profile)
        self.assertEqual(routing.modes, ["walking"])


if __name__ == "__main__":
    unittest.main()
