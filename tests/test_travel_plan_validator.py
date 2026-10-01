"""Offline tests for deterministic real-place itinerary validation."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.travel.validation import TravelPlanValidationError, TravelPlanValidator


TRAVEL_DATA = {
    "accommodations": [{"name": "Harbor Hotel", "address": "1 Harbor Road"}],
    "activities": [
        {"name": "City Museum", "address": "2 Culture Street"},
        {"name": "Old Town", "address": "3 Market Square"},
        {"name": "River Walk", "address": "4 Riverside"},
        {"name": "Freedom Monument", "address": "5 Central Park"},
        {"name": "Peace Memorial", "address": "6 Central Park"},
    ],
}


def valid_plan() -> dict:
    return {
        "selected_accommodation": {"name": "harbor hotel", "address": "Wrong address", "reason": "Central"},
        "itinerary": [
            {"day": 1, "title": "Culture", "activities": [
                {"name": "city museum", "address": "", "reason": "Culture"},
                {"name": "Old Town", "address": "", "reason": "Walk"},
            ]},
            {"day": 2, "title": "Outdoors", "activities": [
                {"name": "River Walk", "address": "", "reason": "Nature"},
                {"name": "Freedom Monument", "address": "", "reason": "History"},
            ]},
        ],
    }


class TravelPlanValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = TravelPlanValidator()

    def test_validates_and_restores_verified_names_and_addresses(self) -> None:
        response = valid_plan()
        self.validator.validate(response, TRAVEL_DATA, duration_days=2)
        self.assertEqual(response["selected_accommodation"]["name"], "Harbor Hotel")
        self.assertEqual(response["selected_accommodation"]["address"], "1 Harbor Road")
        self.assertEqual(response["itinerary"][0]["activities"][0]["name"], "City Museum")
        self.assertEqual(response["itinerary"][0]["activities"][0]["address"], "2 Culture Street")

    def test_rejects_duplicate_activity(self) -> None:
        response = valid_plan()
        response["itinerary"][1]["activities"][0]["name"] = "Old Town"
        with self.assertRaisesRegex(TravelPlanValidationError, "repeated"):
            self.validator.validate(response, TRAVEL_DATA, duration_days=2)

    def test_rejects_two_monuments_on_one_day(self) -> None:
        response = valid_plan()
        response["itinerary"][0]["activities"] = [
            {"name": "Freedom Monument", "address": "", "reason": "History"},
            {"name": "Peace Memorial", "address": "", "reason": "History"},
        ]
        with self.assertRaisesRegex(TravelPlanValidationError, "more than one monument"):
            self.validator.validate(response, TRAVEL_DATA, duration_days=2)

    def test_rejects_missing_or_misordered_days(self) -> None:
        response = valid_plan()
        response["itinerary"][1]["day"] = 3
        with self.assertRaisesRegex(TravelPlanValidationError, "missing or in the wrong order"):
            self.validator.validate(response, TRAVEL_DATA, duration_days=2)

    def test_rejects_place_not_returned_by_geoapify(self) -> None:
        response = valid_plan()
        response["itinerary"][0]["activities"][0]["name"] = "Invented Place"
        with self.assertRaisesRegex(TravelPlanValidationError, "not provided"):
            self.validator.validate(response, TRAVEL_DATA, duration_days=2)

    def test_rejects_overlapping_optional_schedule_entries(self) -> None:
        response = valid_plan()
        response["itinerary"][0]["activities"][0].update({"start_time": "10:00", "end_time": "11:30"})
        response["itinerary"][0]["activities"][1].update({"start_time": "11:00", "end_time": "12:00"})
        with self.assertRaisesRegex(TravelPlanValidationError, "overlap"):
            self.validator.validate(response, TRAVEL_DATA, duration_days=2)


if __name__ == "__main__":
    unittest.main()
