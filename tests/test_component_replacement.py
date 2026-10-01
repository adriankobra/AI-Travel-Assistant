"""Offline transactional checks for activity and food replacement."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.travel.component_replacement import ComponentReplacementError, move_activity, remove_activity, replace_activity, replace_food, replace_hotel
from app.travel.daily_planning import DailyPlanner
from app.travel.food_planning import FoodPlanner
from app.travel.mobility import MobilityProfile
from app.travel.routing import RouteEstimate, UnavailableRoutingService


def place(name: str, category: str, longitude: float) -> dict:
    return {"name": name, "address": f"{name} address", "latitude": 56.95, "longitude": longitude, "categories": [category]}


class ComponentReplacementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hotel = place("Hotel", "accommodation.hotel", 24.10)
        self.museum, self.park = place("Museum", "entertainment.museum", 24.11), place("Park", "leisure.park", 24.12)
        self.food_a, self.food_b, self.food_c = place("Bistro", "catering.restaurant", 24.111), place("Cafe", "catering.cafe", 24.112), place("Market", "commercial.marketplace", 24.113)
        self.hotel_b = place("Hotel B", "accommodation.hotel", 24.13)
        day = {"day": 1, "title": "Day", "activities": [{"name": "Museum", "address": "", "reason": ""}, {"name": "Park", "address": "", "reason": ""}]}
        day_two = {"day": 2, "title": "Day two", "activities": [{"name": "Activity Park", "address": "", "reason": ""}]}
        self.activity_park = place("Activity Park", "entertainment.activity_park", 24.14)
        self.garden = place("Garden", "leisure.park.garden", 24.15)
        router = UnavailableRoutingService()
        DailyPlanner(router).plan([day, day_two], [self.museum, self.park, self.activity_park], [], {}, {}, MobilityProfile(), self.hotel)
        FoodPlanner(router).attach_options([day, day_two], [self.food_a, self.food_b, self.food_c], [], MobilityProfile(), self.hotel)
        self.plan = {"destination": {"city": "Example", "country": "Latvia"}, "selected_accommodation": self.hotel, "itinerary": [day, day_two], "intent": [], "trip_budget": {"total_eur": 800.0, "daily_eur": None, "people": 2, "flights_included": False}, "validation_context": {"travel_data": {"accommodations": [self.hotel, self.hotel_b], "activities": [self.museum, self.park, self.activity_park, self.garden], "food_options": [self.food_a, self.food_b, self.food_c]}, "duration_days": 2, "mobility_profile": {}}}

    def test_activity_replacement_is_new_and_keeps_original_unchanged(self) -> None:
        candidate = replace_activity(self.plan, 1, "Museum", {}, UnavailableRoutingService())
        self.assertEqual(self.plan["itinerary"][0]["activities"][0]["name"], "Museum")
        self.assertEqual(candidate["itinerary"][0]["activities"][0]["name"], "Garden")

    def test_activity_replacement_does_not_turn_a_meal_place_into_an_activity(self) -> None:
        cafe = place("Cafe Activity Candidate", "catering.cafe", 24.105)
        self.plan["validation_context"]["travel_data"]["activities"].insert(0, cafe)
        candidate = replace_activity(self.plan, 1, "Museum", {}, UnavailableRoutingService())
        self.assertEqual(candidate["itinerary"][0]["activities"][0]["name"], "Garden")

    def test_food_replacement_is_new_and_keeps_original_unchanged(self) -> None:
        original = self.plan["itinerary"][0]["meals"][0]["options"][0]["name"]
        candidate = replace_food(self.plan, 1, "lunch", {}, UnavailableRoutingService())
        self.assertEqual(self.plan["itinerary"][0]["meals"][0]["options"][0]["name"], original)
        self.assertNotEqual(candidate["itinerary"][0]["meals"][0]["options"][0]["name"], original)

    def test_move_rebuilds_both_days_without_changing_original(self) -> None:
        candidate = move_activity(self.plan, "Park", 1, 2, {}, UnavailableRoutingService())
        self.assertEqual(len(self.plan["itinerary"][0]["activities"]), 2)
        self.assertEqual([item["name"] for item in candidate["itinerary"][0]["activities"]], ["Museum"])
        self.assertIn("Park", [item["name"] for item in candidate["itinerary"][1]["activities"]])
        self.assertEqual(candidate["itinerary"][0]["route_stops"][0]["name"], "Hotel")

    def test_remove_rebuilds_day_and_keeps_one_activity(self) -> None:
        candidate = remove_activity(self.plan, 1, "Park", {}, UnavailableRoutingService())
        self.assertEqual([item["name"] for item in candidate["itinerary"][0]["activities"]], ["Museum"])
        self.assertTrue(candidate["itinerary"][0]["items"])

    def test_cannot_remove_the_only_activity(self) -> None:
        with self.assertRaises(ComponentReplacementError):
            remove_activity(self.plan, 2, "Activity Park", {}, UnavailableRoutingService())

    def test_hotel_replacement_rebuilds_all_route_stops(self) -> None:
        candidate = replace_hotel(self.plan, {}, UnavailableRoutingService())
        self.assertEqual(candidate["selected_accommodation"]["name"], "Hotel B")
        self.assertTrue(all(day["route_stops"][0]["name"] == "Hotel B" for day in candidate["itinerary"]))

    def test_hotel_replacement_refreshes_intercity_journey_and_fuel(self) -> None:
        class RoadRouter:
            def route(self, origin, destination, transport_mode):
                intercity = "Riga" in {origin.get("name"), destination.get("name")}
                distance = 120_000 if intercity else 1_000
                return RouteEstimate(origin, destination, transport_mode, distance, 80 if intercity else 8, "success", "openrouteservice", "verified")

        self.plan["journey"] = {"origin_place": place("Riga", "place", 24.0)}
        preferences = {"origin": "Riga", "destination_transport": "Car", "journey_vehicle": "Own vehicle", "fuel_consumption_l_per_100km": 5, "fuel_price_eur_per_litre": 2}
        candidate = replace_hotel(self.plan, preferences, RoadRouter())
        self.assertEqual(candidate["journey"]["outbound"]["route"]["destination"]["name"], "Hotel B")
        self.assertEqual(candidate["budget_summary"]["calculated_costs"]["transport_to_destination"], 12)
        self.assertEqual(self.plan["selected_accommodation"]["name"], "Hotel")

    def test_replacement_preserves_budget_and_refreshes_honest_summary(self) -> None:
        candidate = replace_activity(self.plan, 1, "Museum", {}, UnavailableRoutingService())
        self.assertEqual(candidate["trip_budget"]["total_eur"], 800.0)
        self.assertEqual(candidate["budget_summary"]["status"], "price data unavailable")


if __name__ == "__main__":
    unittest.main()
