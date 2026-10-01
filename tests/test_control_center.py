"""Offline coverage for the factual Control Center read models."""
from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from app.travel.control_center import place_explanation, preference_influence, quality_indicators, trip_overview


def activity(name: str, longitude: float) -> dict:
    return {"name": name, "address": f"{name} address", "latitude": 56.95, "longitude": longitude, "categories": ["tourism.sights"]}


class ControlCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        first, second = activity("Museum", 24.10), activity("Park", 24.20)
        self.plan = {
            "destination": {"city": "Riga", "country": "Latvia"},
            "selected_accommodation": {"name": "Hotel", "address": "Hotel address"},
            "trip_strategy": {"pace": "relaxed", "primary_concepts": ["wellness"], "avoided_concepts": ["museums"]},
            "mobility_profile": {"preferred_transport": "walking"},
            "budget_summary": {"status": "price data unavailable"},
            "selected_place_ranking": {"activities": [{"name": "Museum", "matched_concepts": ["culture"], "mobility_score": 1}]},
            "itinerary": [{"day": 1, "date": "2027-06-01", "activities": [first, second], "items": [{"item_type": "travel", "travel_time_data_status": "verified"}, {"item_type": "meal", "options": [{"name": "Bistro"}]}]}],
        }

    def test_overview_preserves_original_requirements(self) -> None:
        view = trip_overview(self.plan, {"travel_style": "Comfortable", "notes": "I want quiet time", "additional_preferences": ["Nature"]})
        self.assertEqual(view["destination"], "Riga, Latvia")
        self.assertEqual(view["pace"], "relaxed")
        self.assertTrue(view["important_preferences"])

    def test_place_explanation_uses_verified_metadata_not_invented_claims(self) -> None:
        messages = place_explanation(self.plan, self.plan["itinerary"][0]["activities"][0], "activity")
        self.assertTrue(any("Verified category match" in value for value in messages))
        self.assertFalse(any("rating" in value.casefold() for value in messages))

    def test_quality_indicators_are_statuses_not_scores(self) -> None:
        indicators = quality_indicators(self.plan)
        self.assertEqual(len(indicators), 8)
        self.assertIn("price data unavailable", [item["status"] for item in indicators])
        self.assertTrue(all("score" not in item for item in indicators))

    def test_preference_influence_only_reports_stored_ranking_evidence(self) -> None:
        self.plan["intent"] = [
            {"concept": "nature", "strength": "high", "polarity": "positive"},
            {"concept": "museum", "strength": "high", "polarity": "negative"},
        ]
        self.plan["selected_place_ranking"] = {
            "activities": [{"name": "Park", "matched_concepts": ["nature"]}],
            "food": [],
            "accommodation": None,
        }
        messages = preference_influence(self.plan)
        self.assertTrue(any("Nature" in message and "Park" in message for message in messages))
        self.assertTrue(any("Avoid Museum" in message for message in messages))
