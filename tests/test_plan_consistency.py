"""Offline regression checks for stale plan data after replacements."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.travel.plan_consistency import PlanConsistencyError, validate_plan_consistency


class PlanConsistencyTests(unittest.TestCase):
    def test_current_hotel_and_activities_match_derived_route_and_timeline(self) -> None:
        plan = {"selected_accommodation": {"name": "New hotel"}, "itinerary": [{
            "activities": [{"name": "Park"}],
            "route_stops": [{"name": "New hotel"}, {"name": "Park"}, {"name": "New hotel"}],
            "items": [{"item_type": "activity", "name": "Park"}],
        }]}
        validate_plan_consistency(plan)

    def test_stale_hotel_route_is_rejected(self) -> None:
        plan = {"selected_accommodation": {"name": "New hotel"}, "itinerary": [{
            "activities": [{"name": "Park"}],
            "route_stops": [{"name": "Old hotel"}, {"name": "Park"}, {"name": "Old hotel"}],
            "items": [{"item_type": "activity", "name": "Park"}],
        }]}
        with self.assertRaises(PlanConsistencyError):
            validate_plan_consistency(plan)


if __name__ == "__main__":
    unittest.main()
