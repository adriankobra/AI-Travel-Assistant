"""Offline checks for constraint parsing and planning behaviour."""
from __future__ import annotations
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from app.travel.constraints import TripConstraints, assess_plan_fit
from app.travel.daily_planning import DailyPlanner
from app.travel.mobility import MobilityProfile
from app.travel.routing import RouteEstimate, RoutingService

class Router(RoutingService):
    def route(self, origin, destination, transport_mode):
        return RouteEstimate(origin, destination, transport_mode, 500, 25, "success", "test", "verified")

def place(name, category, lon):
    return {"name": name, "address": name, "latitude": 56.95, "longitude": lon, "categories": [category]}

class TripConstraintTests(unittest.TestCase):
    def test_parses_natural_language(self):
        value = TripConstraints.from_preferences({"trip_constraints": "No more than 1.5 hours of travel, at least 3 hours of free time, maximum 2 activities per day."})
        self.assertEqual((value.max_daily_travel_minutes, value.min_daily_free_minutes, value.preferred_activity_count), (90, 180, 2))
    def test_free_time_changes_workload(self):
        hotel, museum, park = place("Hotel", "accommodation.hotel", 24.1), place("Museum", "entertainment.museum", 24.11), place("Park", "leisure.park", 24.12)
        day = {"day": 1, "activities": [{"name": "Museum"}, {"name": "Park"}]}
        DailyPlanner(Router()).plan([day], [museum, park], [], {}, {}, MobilityProfile(), hotel, TripConstraints(min_daily_free_minutes=240))
        self.assertGreaterEqual(day["schedule"]["free_time_minutes"], 240)
    def test_travel_cap_changes_selection(self):
        hotel, museum, park = place("Hotel", "accommodation.hotel", 24.1), place("Museum", "entertainment.museum", 24.11), place("Park", "leisure.park", 24.12)
        day = {"day": 1, "activities": [{"name": "Museum"}, {"name": "Park"}]}
        DailyPlanner(Router()).plan([day], [museum, park], [], {}, {}, MobilityProfile(), hotel, TripConstraints(max_daily_travel_minutes=30))
        # One stop needs 25 minutes out and 25 minutes back. Keep a real,
        # minimally populated day, but report that the cap is exceeded.
        self.assertEqual([item["name"] for item in day["activities"]], ["Museum"])
        self.assertEqual(assess_plan_fit({"itinerary": [day]}, TripConstraints(max_daily_travel_minutes=30))[0]["status"], "partially satisfied")
    def test_preferred_start_changes_timeline(self):
        hotel, museum = place("Hotel", "accommodation.hotel", 24.1), place("Museum", "entertainment.museum", 24.11)
        day = {"day": 1, "activities": [{"name": "Museum"}]}
        DailyPlanner(Router()).plan([day], [museum], [], {}, {}, MobilityProfile(), hotel, TripConstraints(preferred_start_minutes=11 * 60))
        self.assertEqual(day["activities"][0]["start_time"], "11:25")
        self.assertEqual(day["schedule"]["day_start_minutes"], 11 * 60)
    def test_activity_cap_changes_selection(self):
        hotel, museum, park = place("Hotel", "accommodation.hotel", 24.1), place("Museum", "entertainment.museum", 24.11), place("Park", "leisure.park", 24.12)
        day = {"day": 1, "activities": [{"name": "Museum"}, {"name": "Park"}]}
        DailyPlanner(Router()).plan([day], [museum, park], [], {}, {}, MobilityProfile(), hotel, TripConstraints(preferred_activity_count=1))
        self.assertEqual([item["name"] for item in day["activities"]], ["Museum"])
    def test_plan_fit_reports_start_and_meal_constraints(self):
        plan = {
            "itinerary": [{
                "schedule": {"day_start_minutes": 11 * 60, "free_time_minutes": 180},
                "activities": [{"end_time": "13:00"}],
                "meals": [{"duration_minutes": 90, "end_time": "14:30"}],
                "items": [],
            }]
        }
        fit = assess_plan_fit(plan, TripConstraints(preferred_start_minutes=11 * 60, meal_duration_minutes=90))
        self.assertEqual(fit, [
            {"constraint": "Preferred start time", "status": "satisfied"},
            {"constraint": "Meal duration", "status": "satisfied"},
        ])
    def test_unverified_route_is_not_falsely_satisfied(self):
        plan = {"itinerary": [{"schedule": {"free_time_minutes": 200}, "activities": [{}], "items": [{"item_type": "travel", "travel_time_data_status": "unavailable"}]}]}
        self.assertEqual(assess_plan_fit(plan, TripConstraints(max_daily_travel_minutes=90))[0]["status"], "unavailable to verify")

    def test_motorcycle_car_road_proxy_does_not_verify_travel_cap(self):
        plan = {"itinerary": [{"schedule": {"planned_transport_mode": "motorcycle"}, "activities": [{}], "items": [{"item_type": "travel", "requested_transport_mode": "motorcycle", "travel_time_data_status": "verified", "travel_duration_minutes": 20}], "return_route": {"data_status": "verified", "duration_minutes": 20}}]}
        self.assertEqual(assess_plan_fit(plan, TripConstraints(max_daily_travel_minutes=90))[0]["status"], "unavailable to verify")
