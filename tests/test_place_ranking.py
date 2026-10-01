"""Offline tests for explainable matching and ranking over Geoapify categories."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.intent_analyzer import IntentPreference
from app.travel.place_ranking import rank_places, unmatched_positive_concepts


PLACES = [
    {"name": "Wellness Centre", "categories": ["healthcare.spa", "leisure.swimming_pool"]},
    {"name": "City Museum", "categories": ["entertainment.museum"]},
    {"name": "Riverside Park", "categories": ["leisure.park"]},
]


class PlaceRankingTests(unittest.TestCase):
    def test_strong_spa_preference_outranks_unrelated_museum(self) -> None:
        intents = [IntentPreference("spa", "very_high", "positive")]
        ranked = rank_places(PLACES, intents)
        self.assertEqual(ranked[0].place["name"], "Wellness Centre")
        self.assertIn("spa", ranked[0].matched_concepts)

    def test_negative_museum_preference_penalizes_museums(self) -> None:
        intents = [IntentPreference("museum", "high", "negative")]
        ranked = rank_places(PLACES, intents)
        self.assertEqual(ranked[-1].place["name"], "City Museum")

    def test_semantic_relaxation_matches_verified_spa_and_park_categories(self) -> None:
        ranked = rank_places(PLACES, [IntentPreference("relaxation", "high", "positive")])
        matching_names = {item.place["name"] for item in ranked if "relaxation" in item.matched_concepts}
        self.assertEqual(matching_names, {"Wellness Centre", "Riverside Park"})

    def test_unknown_request_is_not_fabricated_as_a_verified_match(self) -> None:
        intent = IntentPreference("jet_ski_rental", "high", "positive")
        ranked = rank_places(PLACES, [intent])
        self.assertEqual(unmatched_positive_concepts([intent], ranked), ["jet_ski_rental"])


if __name__ == "__main__":
    unittest.main()
