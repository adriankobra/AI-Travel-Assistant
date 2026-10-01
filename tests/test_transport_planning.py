"""Offline checks for getting-there routes and honest cost provenance."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.travel.budget import TripBudget, budget_summary
from app.ai.travel_recommender import TravelRecommender
from app.travel.constraints import TripConstraints
from app.travel.mobility import MobilityProfile, discovery_radius_meters
from app.travel.place_ranking import rank_places
from app.travel.routing import RouteEstimate
from app.travel.transport_planning import build_journey, fuel_cost, local_fuel_cost


def place(name: str) -> dict:
    return {"name": name, "latitude": 56.95, "longitude": 24.1}


class Router:
    def route(self, origin, destination, transport_mode):
        return RouteEstimate(origin, destination, transport_mode, 100_000, 90, "success", "openrouteservice", "verified")


class TransportPlanningTests(unittest.TestCase):
    def test_driving_uses_verified_round_trip_distance_and_user_inputs(self):
        preferences = {"origin": "Riga", "destination_transport": "Car", "fuel_consumption_l_per_100km": 6, "fuel_price_eur_per_litre": 1.5}
        journey = build_journey(preferences, {"city": "Jurmala", "country": "Latvia"}, place("Hotel"), Router(), geocode=lambda city, country: place("Riga"))
        self.assertEqual(journey["outbound"]["fuel_cost_eur"], 9)
        self.assertEqual(journey["return"]["fuel_cost_eur"], 9)
        summary = budget_summary({"itinerary": [], "journey": journey}, TripBudget(total_eur=100))
        self.assertEqual(summary["calculated_costs"]["transport_to_destination"], 9)
        self.assertEqual(summary["calculated_costs"]["return_journey"], 9)
        self.assertEqual(summary["status"], "partially verifiable")
        self.assertIsNone(summary["verified_costs"]["transport_to_destination"])

    def test_non_driving_mode_has_no_invented_route_or_fare(self):
        journey = build_journey({"origin": "Riga", "destination_transport": "Train"}, {"city": "Tallinn"}, place("Hotel"), Router(), geocode=lambda *_: self.fail("No geocoding needed"))
        self.assertEqual(journey["requested_mode"], "Train")
        self.assertIsNone(journey["outbound"]["distance_meters"])
        self.assertIsNone(journey["return"]["fuel_cost_eur"])

    def test_geocoding_network_failure_degrades_to_unavailable(self):
        def unavailable(*_):
            raise requests.ConnectionError("offline")
        journey = build_journey({"origin": "Riga", "destination_transport": "Car"}, {"city": "Tallinn"}, place("Hotel"), Router(), geocode=unavailable)
        self.assertEqual(journey["outbound"]["status"], "unavailable")

    def test_missing_fuel_inputs_never_create_a_cost(self):
        self.assertIsNone(fuel_cost(100_000, 6, None))
        self.assertIsNone(fuel_cost(None, 6, 1.5))

    def test_simple_budget_request_from_questionnaire_is_understood(self):
        budget = TripBudget.from_preferences({"budget_request": "€1200 for two people"})
        self.assertEqual((budget.total_eur, budget.people), (1200, 2))

    def test_local_fuel_only_counts_verified_car_legs(self):
        plan = {"mobility_profile": {}, "itinerary": [{"items": [
            {"item_type": "travel", "transport_mode": "car", "travel_time_data_status": "verified", "travel_distance_meters": 10_000},
            {"item_type": "travel", "transport_mode": "walking", "travel_time_data_status": "verified", "travel_distance_meters": 3_000},
        ], "return_route": {"transport_mode": "car", "data_status": "verified", "distance_meters": 10_000}}]}
        result = local_fuel_cost(plan, {"fuel_consumption_l_per_100km": 5, "fuel_price_eur_per_litre": 2})
        self.assertEqual(result["distance_meters"], 20_000)
        self.assertEqual(result["cost_eur"], 2)

    def test_routed_regional_day_is_promoted_for_car_not_walking(self):
        hotel = place("Hotel")
        nearby = place("Nearby park")
        nearby["longitude"] = 24.11
        regional = place("Regional nature reserve")
        regional["longitude"] = 24.35
        companion = place("Regional viewpoint")
        companion["longitude"] = 24.36
        ranked = rank_places([nearby, regional, companion], [])
        class RegionalRouter:
            def route(self, origin, destination, transport_mode):
                return RouteEstimate(origin, destination, transport_mode, 20_000, 20, "success", "openrouteservice", "verified")
        recommender = TravelRecommender(client=object(), intent_analyzer=object(), mobility_analyzer=object(), routing_service=RegionalRouter())
        car_plan = {"itinerary": [{"day": 1, "activities": [{"name": nearby["name"]}]}, {"day": 2, "activities": [{"name": nearby["name"]}]}]}
        recommender._ensure_regional_day(car_plan, ranked, [], MobilityProfile(preferred_transport="car", own_car=True, driving_license=True), hotel, TripConstraints())
        self.assertEqual(car_plan["itinerary"][1]["activities"][0]["name"], regional["name"])
        self.assertEqual(car_plan["itinerary"][1]["activities"][1]["name"], companion["name"])
        walking_plan = {"itinerary": [{"day": 1, "activities": [{"name": nearby["name"]}]}, {"day": 2, "activities": [{"name": nearby["name"]}]}]}
        recommender._ensure_regional_day(walking_plan, ranked, [], MobilityProfile(preferred_transport="walking"), hotel, TripConstraints())
        self.assertEqual(walking_plan["itinerary"][1]["activities"][0]["name"], nearby["name"])

    def test_mixed_with_real_car_capability_expands_discovery(self):
        profile = MobilityProfile(preferred_transport="walking", allowed_transport_modes=("walking", "car"), mixed_strategy=True)
        self.assertEqual(discovery_radius_meters(profile), 30_000)


if __name__ == "__main__":
    unittest.main()
