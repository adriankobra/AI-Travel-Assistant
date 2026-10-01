"""Offline coverage for the final itinerary, food, maps, and PDF layers."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest
import re
import zlib
import base64

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.intent_analyzer import IntentPreference
from app.reporting.pdf_report import PDFReportError, build_pdf_report
from app.travel.daily_planning import DailyPlanner
from app.travel.food_planning import FoodPlanner
from app.travel.map_links import build_location_map_url, build_multi_stop_map_url, build_route_map_url
from app.travel.mobility import MobilityProfile
from app.travel.routing import RouteEstimate, UnavailableRoutingService


def place(name: str, category: str = "tourism.sights", longitude: float = 24.10) -> dict:
    return {"name": name, "address": f"{name} address", "latitude": 56.95, "longitude": longitude, "place_id": name.lower().replace(" ", "-"), "categories": [category]}


class VerifiedRouter:
    def route(self, origin: dict, destination: dict, transport_mode: str | None) -> RouteEstimate:
        return RouteEstimate(origin, destination, transport_mode, 650, 8, "success", "openrouteservice", "verified")


class FinalItineraryTests(unittest.TestCase):
    def test_coordinate_location_and_route_urls(self) -> None:
        hotel, museum = place("Hotel"), place("Museum", longitude=24.11)
        url = build_location_map_url(hotel) or ""
        self.assertIn("query=Hotel%2C+address", url)
        self.assertNotIn("query=56.950000%2C24.100000", url)
        route = build_route_map_url(hotel, museum, "walking") or ""
        self.assertIn("origin=56.950000%2C24.100000", route)
        self.assertIn("travelmode=walking", route)

    def test_multi_stop_url_keeps_all_ordered_waypoints_and_rejects_too_many(self) -> None:
        stops = [place(f"P{number}", longitude=24.1 + number / 100) for number in range(4)]
        url = build_multi_stop_map_url(stops, "bicycle") or ""
        self.assertIn("waypoints=56.950000%2C24.110000%7C56.950000%2C24.120000", url)
        self.assertIn("travelmode=bicycling", url)
        self.assertIsNone(build_multi_stop_map_url([place(str(number), longitude=number) for number in range(12)]))

    def test_daily_planner_creates_timeline_and_verified_travel(self) -> None:
        hotel, museum, park = place("Hotel"), place("Museum", longitude=24.11), place("Park", "leisure.park", 24.12)
        days = [{"day": 1, "title": "City", "activities": [{"name": "Museum", "address": "", "reason": "Culture"}, {"name": "Park", "address": "", "reason": "Walk"}]}]
        DailyPlanner(VerifiedRouter()).plan(days, [museum, park], [], {}, {}, MobilityProfile(preferred_transport="walking"), hotel)
        items = days[0]["items"]
        travel = [item for item in items if item["item_type"] == "travel"]
        self.assertTrue(travel)
        self.assertTrue(all(item["travel_time_data_status"] == "verified" for item in travel))
        self.assertTrue(all(item["travel_distance_meters"] == 650 for item in travel))
        self.assertIn("lunch", [meal["meal_type"] for meal in days[0]["meals"]])

    def test_unavailable_route_never_becomes_verified(self) -> None:
        hotel, museum = place("Hotel"), place("Museum", longitude=24.11)
        days = [{"day": 1, "title": "City", "activities": [{"name": "Museum", "address": "", "reason": "Culture"}]}]
        DailyPlanner(UnavailableRoutingService()).plan(days, [museum], [], {}, {}, MobilityProfile(preferred_transport="walking"), hotel)
        travel = next(item for item in days[0]["items"] if item["item_type"] == "travel")
        self.assertEqual(travel["travel_time_data_status"], "unavailable")
        self.assertIsNone(travel.get("travel_distance_meters"))

    def test_food_options_are_real_ranked_and_multiple(self) -> None:
        hotel, museum = place("Hotel"), place("Museum", longitude=24.11)
        foods = [place("Local Bistro", "catering.restaurant", 24.111), place("Cafe Riga", "catering.cafe", 24.112), place("Food Hall", "catering.food_court", 24.113)]
        days = [{"day": 1, "activities": [{"name": "Museum", "address": museum["address"], **museum, "start_time": "10:00", "end_time": "11:30", "duration_minutes": 90, "duration_data_status": "estimated"}], "meals": [{"meal_type": "lunch", "start_time": "12:00", "end_time": "13:00", "options": []}], "items": [{"item_type": "meal", "meal_type": "lunch", "options": []}]}]
        FoodPlanner(VerifiedRouter()).attach_options(days, foods, [IntentPreference("local_food", "high", "positive")], MobilityProfile(preferred_transport="walking"), hotel)
        options = days[0]["meals"][0]["options"]
        self.assertEqual(len(options), 3)
        self.assertTrue(all(option["travel_time_data_status"] == "verified" for option in options))
        self.assertEqual({option["name"] for option in options}, {food["name"] for food in foods})

    def test_food_intent_is_not_overridden_by_nearest_unrelated_option(self) -> None:
        hotel, museum = place("Hotel"), place("Museum", longitude=24.11)
        local = place("Local Bistro", "catering.restaurant", 24.20)
        nearby = place("Nearest Cafe", "catering.cafe", 24.1101)
        days = [{"day": 1, "activities": [{"name": "Museum", "address": museum["address"], **museum, "start_time": "10:00", "end_time": "11:30", "duration_minutes": 90, "duration_data_status": "estimated"}], "meals": [{"meal_type": "lunch", "start_time": "12:00", "end_time": "13:00", "options": []}], "items": [{"item_type": "meal", "meal_type": "lunch", "options": []}]}]
        FoodPlanner(VerifiedRouter()).attach_options(days, [nearby, local], [IntentPreference("local_food", "very_high", "positive")], MobilityProfile(preferred_transport="walking"), hotel)
        self.assertEqual(days[0]["meals"][0]["options"][0]["name"], "Local Bistro")

    def test_pdf_contains_days_times_distances_and_food_and_rejects_invalid_plan(self) -> None:
        hotel, museum = place("Hotel"), place("Museum", longitude=24.11)
        food = place("Local Bistro", "catering.restaurant", 24.112)
        day = {"day": 1, "title": "City", "activities": [{"name": "Museum", "address": "", "reason": "Culture"}]}
        DailyPlanner(VerifiedRouter()).plan([day], [museum], [], {}, {}, MobilityProfile(preferred_transport="walking"), hotel)
        FoodPlanner(VerifiedRouter()).attach_options([day], [food], [], MobilityProfile(preferred_transport="walking"), hotel)
        recommendation = {"destination": {"city": "Riga", "country": "Latvia"}, "selected_accommodation": hotel, "itinerary": [day], "trip_budget": {"total_eur": 800.0, "daily_eur": None, "people": 1, "flights_included": False}, "budget_summary": {"budget": {"total_eur": 800.0}, "verified_costs": {"accommodation": None, "activities": None, "food": None}, "unknown_categories": ["accommodation", "activities", "food"], "status": "price data unavailable"}, "validation_context": {"travel_data": {"accommodations": [hotel], "activities": [museum], "food_options": [food]}, "duration_days": 1, "mobility_profile": {"preferred_transport": "walking"}}}
        pdf = build_pdf_report(recommendation, {"traveller_count": 1, "budget": "€800"})
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)
        recommendation["itinerary"][0]["activities"][0]["name"] = "Invented"
        with self.assertRaises(PDFReportError):
            build_pdf_report(recommendation, {})

    def test_pdf_includes_driving_journey_and_separate_cost_categories(self) -> None:
        hotel, museum = place("Hotel"), place("Museum", longitude=24.11)
        day = {"day": 1, "title": "Drive", "activities": [{"name": "Museum", "address": "", "reason": "Culture"}]}
        DailyPlanner(VerifiedRouter()).plan([day], [museum], [], {}, {}, MobilityProfile(preferred_transport="car"), hotel)
        recommendation = {
            "destination": {"city": "Riga", "country": "Latvia"},
            "selected_accommodation": hotel, "itinerary": [day],
            "journey": {"origin": "Tallinn", "destination": "Riga, Latvia", "requested_mode": "Car", "journey_vehicle": "Own vehicle", "note": "Fuel is calculated from user inputs.",
                        "outbound": {"status": "verified car route", "distance_meters": 300_000, "duration_minutes": 240, "fuel_cost_eur": 30.0},
                        "return": {"status": "verified car route", "distance_meters": 300_000, "duration_minutes": 240, "fuel_cost_eur": 30.0}},
            "budget_summary": {"budget": {"total_eur": 800.0}, "verified_costs": {}, "calculated_costs": {"transport_to_destination": 30.0, "return_journey": 30.0}, "unknown_categories": ["accommodation", "food", "activities", "local_transport"], "status": "partially verifiable"},
            "validation_context": {"travel_data": {"accommodations": [hotel], "activities": [museum], "food_options": []}, "duration_days": 1, "mobility_profile": {"preferred_transport": "car"}},
        }
        pdf = build_pdf_report(recommendation, {"traveller_count": 2})
        content_parts = []
        for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
            try:
                content_parts.append(zlib.decompress(base64.a85decode(stream.strip(), adobe=True)))
            except (ValueError, zlib.error):
                pass
        content = b"\n".join(content_parts)
        self.assertIn(b"Getting there", content)
        self.assertIn(b"Return journey", content)
        self.assertIn(b"Own vehicle", content)


if __name__ == "__main__":
    unittest.main()
