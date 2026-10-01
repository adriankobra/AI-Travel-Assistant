"""Offline regression coverage for diversity, food fallback, and safe rotation."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.travel.food_planning import FoodPlanner
from app.travel.map_links import build_location_map_url
from app.travel.spatial_diversity import diversify


def place(name: str, longitude: float, category: str = "catering.restaurant") -> dict:
    return {"name": name, "address": f"{name}, Main Street", "city": "Example", "country": "Latvia", "latitude": 56.95, "longitude": longitude, "categories": [category]}


class RegenerationQualityTests(unittest.TestCase):
    def test_diversity_interleaves_separate_coordinate_areas(self) -> None:
        ranked = [place("Central one", 24.10), place("Central two", 24.1001), place("West", 24.06), place("East", 24.16)]
        result = diversify(ranked)
        self.assertEqual(result[0]["name"], "Central one")
        self.assertNotEqual(result[1]["name"], "Central two")

    def test_food_fallback_reuses_verified_food_only_after_pool_exhaustion(self) -> None:
        foods = [place("Bistro", 24.11), place("Cafe", 24.12, "catering.cafe")]
        itinerary = [{"activities": [place("Museum", 24.10, "entertainment.museum")], "meals": [
            {"meal_type": "lunch", "options": []}, {"meal_type": "dinner", "options": []}], "items": []}]
        FoodPlanner().attach_options(itinerary, foods, [], None, place("Hotel", 24.10))
        meals = itinerary[0]["meals"]
        self.assertTrue(meals[0]["options"])
        self.assertTrue(meals[1]["options"])
        self.assertTrue(all("catering" in " ".join(item["categories"]) for meal in meals for item in meal["options"]))

    def test_name_address_map_search_is_encoded_before_coordinate_fallback(self) -> None:
        url = build_location_map_url(place("Spa & Sauna", 24.11)) or ""
        self.assertIn("Spa+%26+Sauna", url)
        self.assertIn("Main+Street", url)
        self.assertNotIn("56.950000", url)

    def test_name_is_not_duplicated_when_geoapify_address_already_includes_it(self) -> None:
        url = build_location_map_url({**place("Spa", 24.11), "address": "Spa, Main Street"}) or ""
        self.assertIn("query=Spa%2C+Main+Street", url)
        self.assertNotIn("Spa%2C+Spa", url)


if __name__ == "__main__":
    unittest.main()
