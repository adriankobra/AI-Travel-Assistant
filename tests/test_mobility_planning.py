"""Offline tests for mobility profiles, routing abstraction, and constraints."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.intent_analyzer import IntentPreference
from app.ai.travel_recommender import TravelRecommender
from app.travel.daily_planning import DailyPlanner
from app.travel.mobility import MobilityProfile
from app.travel.place_ranking import rank_places
from app.travel.routing import UnavailableRoutingService
from app.travel.validation import TravelPlanValidationError, TravelPlanValidator


def place(name: str, categories: list[str], distance: float | None = None) -> dict:
    result = {"name": name, "address": f"{name} address", "categories": categories, "latitude": 58.38, "longitude": 24.50}
    if distance is not None:
        result["distance_meters"] = distance
    return result


class StubIntentAnalyzer:
    def analyze(self, _preferences: dict) -> list[IntentPreference]:
        return [IntentPreference("spa", "high", "positive")]


class StubMobilityAnalyzer:
    def analyze(self, _preferences: dict) -> MobilityProfile:
        return MobilityProfile(allowed_transport_modes=("walking",), walking_preference="very_high", car_usage=False, public_transport_usage=False)


class StubClient:
    def __init__(self) -> None:
        self.prompt = ""

    def send_structured_prompt(self, _prompt: str, **_kwargs: object) -> dict:
        self.prompt = _prompt
        return {"selected_accommodation": {"name": "Hotel", "address": "", "reason": ""}, "itinerary": [{"day": 1, "title": "Day", "activities": [{"name": "Near Spa", "address": "", "reason": ""}]}]}


class MobilityPlanningTests(unittest.TestCase):
    def test_walking_only_profile_keeps_other_transport_disallowed(self) -> None:
        profile = MobilityProfile.from_dict({"allowed_transport_modes": ["walking"], "walking_preference": "very_high", "car_usage": False, "public_transport_usage": False})
        self.assertTrue(profile.walking_only)
        self.assertFalse(profile.allows("car"))

    def test_public_transport_preference_is_not_car_capability(self) -> None:
        profile = MobilityProfile.from_dict({"preferred_transport": "public_transport", "public_transport_preference": "high", "driving_license": True})
        self.assertEqual(profile.preferred_transport, "public_transport")
        self.assertTrue(profile.driving_license)
        self.assertIsNone(profile.car_usage)

    def test_license_and_car_rental_are_separate(self) -> None:
        profile = MobilityProfile.from_dict({"driving_license": True, "rental_car_allowed": True, "preferred_transport": "car"})
        self.assertTrue(profile.driving_license)
        self.assertTrue(profile.rental_car_allowed)
        self.assertFalse(profile.own_car is True)

    def test_own_car_does_not_require_rental(self) -> None:
        profile = MobilityProfile.from_dict({"own_car": True, "car_usage": True})
        self.assertTrue(profile.own_car)
        self.assertIsNone(profile.rental_car_allowed)

    def test_license_without_desire_to_drive_is_preserved(self) -> None:
        profile = MobilityProfile.from_dict({"driving_license": True, "car_usage": False, "preferred_transport": "walking"})
        self.assertTrue(profile.driving_license)
        self.assertFalse(profile.car_usage)
        self.assertEqual(profile.preferred_transport, "walking")

    def test_no_driving_rejects_car_rental(self) -> None:
        response = {"selected_accommodation": {"name": "Hotel", "address": ""}, "itinerary": [{"day": 1, "activities": [{"name": "Car Hire", "address": ""}]}]}
        data = {"accommodations": [place("Hotel", ["accommodation.hotel"])], "activities": [place("Car Hire", ["rental.car"])]}
        with self.assertRaisesRegex(TravelPlanValidationError, "does not allow car rental"):
            TravelPlanValidator().validate(response, data, 1, MobilityProfile(rental_car_allowed=False))

    def test_bicycle_preference_ranks_verified_bicycle_place(self) -> None:
        ranked = rank_places([place("Park", ["leisure.park"]), place("Bike Hire", ["rental.bicycle"])], [], MobilityProfile(bicycle_preference="very_high"))
        self.assertEqual(ranked[0].place["name"], "Bike Hire")

    def test_mixed_city_and_outside_city_strategy_is_not_overconstrained(self) -> None:
        profile = MobilityProfile.from_dict({"mixed_strategy": True, "city_transport": "walking", "outside_city_transport": "car", "allowed_transport_modes": ["walking", "car"]})
        self.assertTrue(profile.mixed_strategy)
        self.assertTrue(profile.allows("walking"))
        self.assertTrue(profile.allows("car"))

    def test_unknown_mobility_does_not_assume_car_or_license(self) -> None:
        profile = MobilityProfile.unknown()
        self.assertIsNone(profile.driving_license)
        self.assertIsNone(profile.own_car)
        self.assertIsNone(profile.allowed_transport_modes)
        self.assertIsNone(profile.mixed_strategy)

    def test_unknown_mixed_strategy_is_not_coerced_to_false(self) -> None:
        profile = MobilityProfile.from_dict({"mixed_strategy": None})
        self.assertIsNone(profile.mixed_strategy)

    def test_spa_preference_and_walking_only_still_rank_near_spa(self) -> None:
        profile = MobilityProfile(allowed_transport_modes=("walking",), walking_preference="very_high", car_usage=False, public_transport_usage=False)
        ranked = rank_places([place("Near Spa", ["leisure.spa"], 500), place("Far Spa", ["leisure.spa"], 9000)], [IntentPreference("spa", "high", "positive")], profile)
        self.assertEqual(ranked[0].place["name"], "Near Spa")

    def test_far_place_with_car_available_remains_candidate(self) -> None:
        profile = MobilityProfile(allowed_transport_modes=("car",), own_car=True, car_usage=True)
        ranked = rank_places([place("Far Spa", ["leisure.spa"], 9000)], [], profile)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].mobility_score, 0)

    def test_far_place_with_walking_only_is_rejected_by_validator(self) -> None:
        response = {"selected_accommodation": {"name": "Hotel", "address": ""}, "itinerary": [{"day": 1, "activities": [{"name": "Far Spa", "address": ""}]}]}
        data = {"accommodations": [place("Hotel", ["accommodation.hotel"])], "activities": [place("Far Spa", ["leisure.spa"], 9000)]}
        profile = MobilityProfile(allowed_transport_modes=("walking",), walking_preference="very_high", car_usage=False, public_transport_usage=False)
        with self.assertRaisesRegex(TravelPlanValidationError, "far-away"):
            TravelPlanValidator().validate(response, data, 1, profile)

    def test_routing_default_has_no_invented_duration(self) -> None:
        route = UnavailableRoutingService().route(place("A", []), place("B", []), "walking")
        self.assertEqual(route.status, "unavailable")
        self.assertIsNone(route.duration_minutes)
        self.assertEqual(route.data_status, "unavailable")

    def test_daily_planner_keeps_transition_buffer_and_marks_route_unavailable(self) -> None:
        itinerary = [{"day": 1, "activities": [{"name": "A", "address": "", "reason": ""}, {"name": "B", "address": "", "reason": ""}]}]
        DailyPlanner().plan(itinerary, [place("A", ["leisure.park"]), place("B", ["leisure.park"])], [], {}, {}, MobilityProfile(preferred_transport="walking"))
        second = itinerary[0]["activities"][1]
        self.assertEqual(second["route"]["status"], "unavailable")
        self.assertEqual(second["travel_time_data_status"], "unavailable")
        self.assertEqual(second["transition_buffer_status"], "estimated")

    def test_mobility_profile_survives_recommender(self) -> None:
        data = {"accommodations": [place("Hotel", ["accommodation.hotel"])], "activities": [place("Near Spa", ["leisure.spa"], 500)]}
        client = StubClient()
        result = TravelRecommender(client=client, intent_analyzer=StubIntentAnalyzer(), mobility_analyzer=StubMobilityAnalyzer()).recommend({}, {}, data, 1)
        self.assertTrue(result["mobility_profile"]["allowed_transport_modes"] == ["walking"])
        self.assertIn("MOBILITY PROFILE", client.prompt)


if __name__ == "__main__":
    unittest.main()
