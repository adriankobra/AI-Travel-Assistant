"""Offline integration test for intent analysis, ranking, recommender, and validation."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.intent_analyzer import IntentPreference
from app.ai.travel_recommender import TravelRecommender
from app.travel.place_ranking import rank_places


class StubIntentAnalyzer:
    def analyze(self, _preferences: dict) -> list[IntentPreference]:
        return [IntentPreference("spa", "very_high", "positive")]


class StubRecommendationClient:
    def __init__(self) -> None:
        self.prompt = ""

    def send_structured_prompt(self, prompt: str, **_: object) -> dict:
        self.prompt = prompt
        return {
            "selected_accommodation": {"name": "Wellness Hotel", "address": "", "reason": "Preference match"},
            "itinerary": [{"day": 1, "title": "Wellness day", "activities": [
                {"name": "Thermal Spa", "address": "", "reason": "Preference match"},
                {"name": "City Museum", "address": "", "reason": "Culture"},
            ]}],
        }


class RecommenderIntentIntegrationTests(unittest.TestCase):
    def test_meal_only_places_are_not_primary_activities_when_real_experiences_exist(self) -> None:
        ranked = rank_places(
            [
                {"name": "Verified Cafe", "categories": ["catering.cafe"]},
                {"name": "Verified Museum", "categories": ["entertainment.museum"]},
            ],
            [],
        )
        primary = TravelRecommender._primary_activity_ranking(ranked)
        self.assertEqual([item.place["name"] for item in primary], ["Verified Museum"])

    def test_meal_only_places_remain_a_fallback_when_no_activity_exists(self) -> None:
        ranked = rank_places(
            [{"name": "Verified Cafe", "categories": ["catering.cafe"]}],
            [],
        )
        primary = TravelRecommender._primary_activity_ranking(ranked)
        self.assertEqual([item.place["name"] for item in primary], ["Verified Cafe"])

    def test_ranks_verified_spa_places_before_other_places_and_keeps_metadata(self) -> None:
        client = StubRecommendationClient()
        travel_data = {
            "accommodations": [
                {"name": "Plain Hotel", "address": "1 Main", "categories": ["accommodation.hotel"]},
                {"name": "Wellness Hotel", "address": "2 Spa", "categories": ["accommodation.hotel", "healthcare.spa"]},
            ],
            "activities": [
                {"name": "City Museum", "address": "3 Art", "categories": ["entertainment.museum"]},
                {"name": "Thermal Spa", "address": "4 Water", "categories": ["healthcare.spa"]},
            ],
        }
        result = TravelRecommender(client=client, intent_analyzer=StubIntentAnalyzer()).recommend(
            preferences={"notes": "I want a spa"}, destination={"city": "Example", "country": "Example"},
            travel_data=travel_data, duration_days=1,
        )
        self.assertLess(client.prompt.index("Wellness Hotel"), client.prompt.index("Plain Hotel"))
        self.assertLess(client.prompt.index("Thermal Spa"), client.prompt.index("City Museum"))
        self.assertEqual(result["intent"][0]["concept"], "spa")
        self.assertEqual(result["unverified_activity_preference_concepts"], [])
        self.assertEqual(
            result["selected_accommodation"]["reason"],
            "Prioritized because verified Geoapify categories match: spa.",
        )
        self.assertEqual(result["itinerary"][0]["route_stops"][0]["name"], "Wellness Hotel")
        self.assertEqual(result["itinerary"][0]["items"][0]["name"], "Wellness Hotel")
        ranking = result["selected_place_ranking"]["accommodation"]
        self.assertEqual(ranking["preference_score"], 8)
        self.assertIn("No verified rating", ranking["quality_evidence"])

    def test_accommodation_keeps_generic_top_ranked_candidate(self) -> None:
        candidates = [
            {"name": "Preference match", "categories": ["accommodation.hotel", "tourism.viewpoint"]},
            {"name": "Lower match", "categories": ["accommodation.hotel"]},
        ]
        self.assertEqual(
            TravelRecommender._select_accommodation(candidates, {"notes": "I want views"}, {"city": "Example"})["name"],
            "Preference match",
        )

    def test_final_guard_replaces_a_strongly_disliked_verified_category(self) -> None:
        intents = [IntentPreference("museum", "very_high", "negative")]
        ranked = rank_places(
            [
                {"name": "Museum", "address": "1 Art", "categories": ["entertainment.museum"]},
                {"name": "Park", "address": "2 Green", "categories": ["leisure.park"]},
            ],
            intents,
        )
        response = {"itinerary": [{"day": 1, "activities": [{"name": "Museum", "address": "", "reason": ""}]}]}
        TravelRecommender._remove_strong_negative_conflicts(response, ranked)
        self.assertEqual(response["itinerary"][0]["activities"][0]["name"], "Park")

    def test_final_guard_uses_another_verified_area_without_displacing_priority_match(self) -> None:
        intents = [IntentPreference("nature", "very_high", "positive")]
        places = [
            {"name": "Nature Park", "address": "1", "latitude": 56.95, "longitude": 24.10, "categories": ["leisure.park"]},
            {"name": "Nearby Sight", "address": "2", "latitude": 56.9501, "longitude": 24.1001, "categories": ["tourism.sights"]},
            {"name": "Nearby Garden", "address": "3", "latitude": 56.9502, "longitude": 24.1002, "categories": ["leisure.park.garden"]},
            {"name": "Far Viewpoint", "address": "4", "latitude": 57.05, "longitude": 24.40, "categories": ["tourism.sights"]},
        ]
        ranked = rank_places(places, intents)
        response = {"itinerary": [{"day": 1, "activities": [
            {"name": "Nature Park", "address": "", "reason": ""},
            {"name": "Nearby Sight", "address": "", "reason": ""},
        ]}]}
        TravelRecommender._improve_spatial_diversity(response, ranked, intents)
        names = [item["name"] for item in response["itinerary"][0]["activities"]]
        self.assertIn("Nature Park", names)
        self.assertIn("Far Viewpoint", names)


if __name__ == "__main__":
    unittest.main()
