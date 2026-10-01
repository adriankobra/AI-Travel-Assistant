"""Offline behavioural tests for conservative, variable daily planning."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.intent_analyzer import IntentPreference
from app.travel.daily_planning import DailyPlanner


def place(name: str, categories: list[str], latitude: float = 58.38, longitude: float = 24.50, **extra: object) -> dict:
    return {
        "name": name,
        "address": f"{name} address",
        "categories": categories,
        "latitude": latitude,
        "longitude": longitude,
        **extra,
    }


def itinerary(*days: list[str]) -> list[dict]:
    return [
        {
            "day": number,
            "title": f"Day {number}",
            "activities": [{"name": name, "address": "", "reason": "Selected"} for name in names],
        }
        for number, names in enumerate(days, start=1)
    ]


class DailyPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = DailyPlanner()
        self.places = [
            place("Thermal Spa", ["healthcare.spa"]),
            place("Art Museum", ["entertainment.museum"], longitude=24.51),
            place("Old Town", ["tourism.sights"], longitude=24.52),
            place("Central Park", ["leisure.park"], longitude=24.53),
            place("Harbour Walk", ["outdoor.activity"], longitude=24.54),
            place("Local Bistro", ["catering.restaurant"], longitude=24.55),
        ]

    def _plan(self, days: list[dict], intents: list[IntentPreference]) -> list[dict]:
        self.planner.plan(days, self.places, intents, {"travel_style": "Balanced"}, {"city": "Example"})
        return days

    def test_relaxed_trip_has_fewer_activities_and_free_time(self) -> None:
        days = self._plan(
            itinerary(["Thermal Spa", "Art Museum", "Central Park"]),
            [IntentPreference("relaxation", "very_high", "positive")],
        )
        self.assertEqual([item["name"] for item in days[0]["activities"]], ["Thermal Spa"])
        self.assertGreater(days[0]["schedule"]["free_time_minutes"], 180)

    def test_active_trip_can_fit_more_shorter_activities(self) -> None:
        days = self._plan(
            itinerary(["Old Town", "Central Park", "Harbour Walk", "Local Bistro"]),
            [IntentPreference("active", "very_high", "positive")],
        )
        self.assertEqual(len(days[0]["activities"]), 4)

    def test_sightseeing_trip_uses_realistic_museum_estimate(self) -> None:
        days = self._plan(
            itinerary(["Art Museum", "Old Town", "Central Park"]),
            [IntentPreference("sightseeing", "high", "positive")],
        )
        self.assertEqual(days[0]["activities"][0]["duration_minutes"], 120)
        self.assertEqual(days[0]["activities"][0]["duration_data_status"], "estimated")

    def test_spa_and_relaxation_does_not_fill_every_available_minute(self) -> None:
        days = self._plan(
            itinerary(["Thermal Spa", "Old Town", "Central Park"]),
            [IntentPreference("spa", "very_high", "positive")],
        )
        schedule = days[0]["schedule"]
        self.assertEqual(len(days[0]["activities"]), 1)
        self.assertGreater(schedule["reserved_break_minutes"], 0)
        self.assertGreater(schedule["free_time_minutes"], 0)

    def test_different_category_durations_and_verified_duration(self) -> None:
        places = [
            place("Verified Tour", ["tourism.sights"], duration_minutes=135, duration_source="partner API"),
            place("Museum", ["entertainment.museum"]),
            place("Park", ["leisure.park"]),
        ]
        days = itinerary(["Verified Tour", "Museum", "Park"])
        self.planner.plan(days, places, [], {}, {})
        activities = days[0]["activities"]
        self.assertEqual([item["duration_minutes"] for item in activities], [135, 120])
        self.assertEqual(activities[0]["duration_data_status"], "verified")
        self.assertEqual(activities[1]["duration_data_status"], "estimated")

    def test_missing_duration_is_explicit_conservative_estimate(self) -> None:
        days = self._plan(itinerary(["Old Town"]), [])
        activity = days[0]["activities"][0]
        self.assertEqual(activity["duration_data_status"], "estimated")
        self.assertIn("Geoapify duration unavailable", activity["duration_source"])

    def test_days_can_have_different_activity_counts(self) -> None:
        days = self._plan(
            itinerary(["Thermal Spa", "Art Museum"], ["Old Town", "Central Park", "Harbour Walk", "Local Bistro"]),
            [IntentPreference("relaxation", "very_high", "positive")],
        )
        self.assertEqual(len(days[0]["activities"]), 1)
        self.assertGreater(len(days[1]["activities"]), len(days[0]["activities"]))

    def test_schedules_do_not_overlap(self) -> None:
        days = self._plan(itinerary(["Old Town", "Central Park", "Harbour Walk"]), [])
        activities = days[0]["activities"]
        ends = [self._to_minutes(item["end_time"]) for item in activities]
        starts = [self._to_minutes(item["start_time"]) for item in activities]
        self.assertTrue(all(next_start >= end for end, next_start in zip(ends, starts[1:])))
        self.assertTrue(all(item["travel_time_data_status"] == "unavailable" for item in activities))

    @staticmethod
    def _to_minutes(value: str) -> int:
        hour, minute = value.split(":")
        return int(hour) * 60 + int(minute)


if __name__ == "__main__":
    unittest.main()
