"""Regression tests for safe destination geocoding."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.travel.geocoding import get_coordinates


class GeocodingTests(unittest.TestCase):
    @patch("app.travel.geocoding.requests.get")
    def test_rejects_a_street_false_match_for_a_destination(self, request_get: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "features": [{"properties": {
                "result_type": "street", "name": "Via Val Gardena",
                "city": "Grottammare", "country": "Italy", "lat": 42.9, "lon": 13.8,
            }}]
        }
        request_get.return_value = response

        with self.assertRaisesRegex(ValueError, "geographic destination match"):
            get_coordinates("Val Gardena, Dolomites", "Italy")

    @patch("app.travel.geocoding.requests.get")
    def test_keeps_a_city_level_destination_match(self, request_get: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "features": [{"properties": {
                "result_type": "city", "city": "Pärnu", "country": "Estonia", "lat": 58.3859, "lon": 24.4971,
            }}]
        }
        request_get.return_value = response

        self.assertEqual(
            get_coordinates("Pärnu", "Estonia"),
            {"city": "Pärnu", "country": "Estonia", "latitude": 58.3859, "longitude": 24.4971},
        )


if __name__ == "__main__":
    unittest.main()
