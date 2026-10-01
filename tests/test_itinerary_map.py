"""Regression coverage for map route markers derived from the current plan."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ui.itinerary_map import _point


class ItineraryMapTests(unittest.TestCase):
    def test_activity_points_are_explicit_route_stops_not_label_inference(self) -> None:
        point = _point({"name": "Park", "latitude": 56.95, "longitude": 24.1}, "Day 1 · Stop 1", "#0ea5c6", route_stop=True)
        self.assertTrue(point and point["route_stop"])
        self.assertEqual(point["kind"], "Day 1 · Stop 1")


if __name__ == "__main__":
    unittest.main()
