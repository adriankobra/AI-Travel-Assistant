"""Offline tests for expanded, factual Geoapify place discovery and ranking."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.intent_analyzer import IntentPreference
from app.travel.category_config import ACTIVITY_CATEGORIES, ACTIVITY_CATEGORY_GROUPS
from app.travel.place import Place, deduplicate_places
from app.travel.place_ranking import rank_places, unmatched_positive_concepts


def mock_place(name: str, categories: list[str], **metadata: object) -> dict:
    return Place(
        name=name,
        address=f"{name} address",
        latitude=metadata.pop("latitude", 58.38),
        longitude=metadata.pop("longitude", 24.50),
        place_id=metadata.pop("place_id", name.casefold().replace(" ", "-")),
        categories=categories,
        **metadata,
    ).to_dict()


PLACES = [
    mock_place("Wellness House", ["leisure.spa"]),
    mock_place("Seaside Beach", ["beach", "natural.coastal"]),
    mock_place("Bike Station", ["rental.bicycle"]),
    mock_place("Car Station", ["rental.car"]),
    mock_place("Local Kitchen", ["catering.restaurant"]),
    mock_place("Coffee Corner", ["catering.cafe"]),
    mock_place("Evening Pub", ["catering.pub"]),
    mock_place("Forest Trail", ["natural.forest", "highway.path"]),
    mock_place("Playground", ["leisure.playground"]),
    mock_place("Town Mall", ["commercial.shopping_mall"]),
    mock_place("City Museum", ["entertainment.museum"]),
]


class ExpandedDiscoveryTests(unittest.TestCase):
    def test_supported_groups_are_flattened_without_duplicate_query_categories(self) -> None:
        self.assertGreaterEqual(len(ACTIVITY_CATEGORY_GROUPS), 8)
        self.assertEqual(len(ACTIVITY_CATEGORIES), len(set(ACTIVITY_CATEGORIES)))
        self.assertLessEqual(len(ACTIVITY_CATEGORIES), 100)
        self.assertIn("rental.bicycle", ACTIVITY_CATEGORIES)
        self.assertIn("catering.restaurant", ACTIVITY_CATEGORIES)
        self.assertIn("leisure.spa", ACTIVITY_CATEGORIES)

    def test_expected_concepts_match_only_verified_category_metadata(self) -> None:
        expectations = {
            "spa": "Wellness House",
            "beach": "Seaside Beach",
            "water_activities": "Seaside Beach",
            "bike_rental": "Bike Station",
            "car_rental": "Car Station",
            "local_food": "Local Kitchen",
            "cafe": "Coffee Corner",
            "nightlife": "Evening Pub",
            "hiking": "Forest Trail",
            "family": "Playground",
            "shopping": "Town Mall",
        }
        for concept, expected_name in expectations.items():
            with self.subTest(concept=concept):
                ranked = rank_places(PLACES, [IntentPreference(concept, "very_high", "positive")])
                self.assertEqual(ranked[0].place["name"], expected_name)
                self.assertIn(concept, ranked[0].matched_concepts)

    def test_negative_museum_preference_remains_a_penalty(self) -> None:
        ranked = rank_places(PLACES, [IntentPreference("museum", "high", "negative")])
        self.assertEqual(ranked[-1].place["name"], "City Museum")

    def test_unsupported_jet_ski_intent_stays_unverified(self) -> None:
        intent = IntentPreference("jet_ski_rental", "high", "positive")
        ranked = rank_places(PLACES, [intent])
        self.assertEqual(unmatched_positive_concepts([intent], ranked), ["jet_ski_rental"])
        self.assertFalse(any(item.matched_concepts for item in ranked))

    def test_same_place_from_multiple_categories_is_deduplicated_and_categories_are_retained(self) -> None:
        duplicate_id = "geoapify-place-id"
        bike = Place("Harbour Hub", "Harbour", 58.38, 24.50, duplicate_id, ["rental.bicycle"])
        cafe = Place("Harbour Hub", "Harbour", 58.38, 24.50, duplicate_id, ["catering.cafe"])
        deduplicated = deduplicate_places([bike, cafe])
        self.assertEqual(len(deduplicated), 1)
        self.assertEqual(deduplicated[0].categories, ["rental.bicycle", "catering.cafe"])

    def test_place_dto_preserves_available_geoapify_metadata(self) -> None:
        place = Place.from_geoapify({
            "name": "Example Spa", "formatted": "1 Coast Road", "lat": 58.38, "lon": 24.50,
            "place_id": "place-1", "categories": ["leisure.spa"], "city": "Example City",
            "country": "Example Country", "datasource": {"sourcename": "openstreetmap", "raw": {"opening_hours": "ignored"}},
        })
        assert place is not None
        result = place.to_dict()
        self.assertEqual(result["city"], "Example City")
        self.assertEqual(result["country"], "Example Country")
        self.assertEqual(result["datasource"], {"sourcename": "openstreetmap"})

    def test_existing_spa_over_museum_ranking_behaviour_is_preserved(self) -> None:
        ranked = rank_places(PLACES, [IntentPreference("spa", "very_high", "positive")])
        self.assertEqual(ranked[0].place["name"], "Wellness House")
        self.assertNotEqual(ranked[-1].place["name"], "Wellness House")


if __name__ == "__main__":
    unittest.main()
