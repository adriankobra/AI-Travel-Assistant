"""Offline regional-plan behavior with factual sample places and mock ORS legs."""

from __future__ import annotations

from copy import deepcopy
import base64
import re
import sys
from pathlib import Path
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.intent_analyzer import IntentPreference
from app.ai.travel_recommender import TravelRecommender
from app.travel.budget import TripBudget, budget_summary
from app.travel.component_replacement import remove_activity
from app.travel.constraints import TripConstraints, assess_plan_fit
from app.travel.daily_planning import DailyPlanner
from app.travel.mobility import MobilityProfile
from app.travel.place_ranking import rank_places
from app.travel.plan_consistency import PlanConsistencyError, validate_plan_consistency
from app.travel.regional_planning import fill_sparse_days, keep_selected_places_mobility_compatible, promote_regional_day, refresh_regional_explanations, direct_km
from app.travel.routing import RouteEstimate
from app.travel.trip_strategy import TripStrategy
from app.travel.validation import TravelPlanValidator
from app.ui.itinerary_map import itinerary_map_data
from app.reporting.pdf_report import build_pdf_report
from streamlit.testing.v1 import AppTest


def place(name: str, longitude: float, category: str = "leisure.park") -> dict:
    return {"name": name, "address": f"{name} address", "latitude": 56.95, "longitude": longitude, "place_id": name.lower().replace(" ", "-"), "categories": [category]}


class RegionalRouter:
    def __init__(self, available: bool = True) -> None:
        self.available = available

    def route(self, origin, destination, transport_mode):
        km = direct_km(origin, destination) or 0.1
        if not self.available:
            return RouteEstimate(origin, destination, transport_mode, None, None, "unavailable", None, "unavailable")
        return RouteEstimate(origin, destination, transport_mode, round(km * 1200), 30 if km >= 8 else 8, "success", "openrouteservice", "verified")


class RegionalPlanningTests(unittest.TestCase):
    def setUp(self):
        self.hotel = place("Hotel", 24.10, "accommodation.hotel")
        self.near = place("Local park", 24.11)
        self.local_two = place("Local garden", 24.12, "leisure.park.garden")
        self.local_extra = place("Local promenade", 24.115)
        self.regional = place("Nature reserve", 24.39, "leisure.park.nature_reserve")
        self.companion = place("Forest viewpoint", 24.40, "natural.forest")
        self.activities = [self.near, self.local_two, self.local_extra, self.regional, self.companion]
        self.intents = [IntentPreference("nature", "high", "positive")]
        self.ranked = rank_places(self.activities, self.intents)
        self.strategy = TripStrategy.from_intents(self.intents)
        self.car = MobilityProfile(preferred_transport="car", allowed_transport_modes=("car",), own_car=True, driving_license=True)
        self.days = [
            {"day": 1, "title": "Local", "activities": [{"name": self.near["name"], "address": "", "reason": ""}]},
            {"day": 2, "title": "Explore", "activities": [{"name": self.local_two["name"], "address": "", "reason": ""}]},
        ]

    def test_car_day_trip_has_two_real_stops_and_verified_return(self):
        days = deepcopy(self.days)
        router = RegionalRouter()
        self.assertTrue(promote_regional_day(days, self.ranked, self.hotel, self.car, TripConstraints(max_daily_travel_minutes=90), self.strategy, router))
        self.assertEqual(len(days[1]["activities"]), 2)
        self.assertEqual({item["name"] for item in days[1]["activities"]}, {"Nature reserve", "Forest viewpoint"})
        DailyPlanner(router).plan(days, self.activities, self.intents, {}, {}, self.car, self.hotel, TripConstraints(max_daily_travel_minutes=90))
        plan = {"selected_accommodation": self.hotel, "itinerary": days}
        TravelPlanValidator().validate(plan, {"accommodations": [self.hotel], "activities": self.activities}, 2, self.car)
        refresh_regional_explanations(plan)
        validate_plan_consistency(plan)
        stale = deepcopy(plan)
        stale["itinerary"][1]["regional_trip"]["round_trip_distance_meters"] += 5000
        with self.assertRaises(PlanConsistencyError):
            validate_plan_consistency(stale)
        self.assertEqual(len(days[1]["activities"]), 2)
        self.assertEqual(days[1]["return_route"]["data_status"], "verified")
        lunch = next(meal for meal in days[1]["meals"] if meal["meal_type"] == "lunch")
        self.assertLessEqual(days[1]["activities"][0]["end_time"], lunch["start_time"])
        self.assertLessEqual(lunch["end_time"], days[1]["activities"][1]["start_time"])
        self.assertEqual(assess_plan_fit(plan, TripConstraints(max_daily_travel_minutes=90))[0]["status"], "satisfied")
        self.assertEqual(len(itinerary_map_data(self.hotel, days)["routes"][1]["coordinates"]), 4)
        self.assertTrue(any(point["kind"] == "Day 2 · Stop 2" for point in itinerary_map_data(self.hotel, days)["points"]))
        plan["mobility_profile"] = self.car.to_dict()
        plan["journey"] = {"fuel_consumption_l_per_100km": 6, "fuel_price_eur_per_litre": 1.5}
        summary = budget_summary(plan, TripBudget(total_eur=500))
        self.assertGreater(summary["calculated_costs"]["local_transport"], 0)
        self.assertEqual(summary["status"], "partially verifiable")
        local_days = deepcopy(self.days)
        DailyPlanner(router).plan(local_days, self.activities, self.intents, {}, {}, self.car, self.hotel)
        local_only = budget_summary({"itinerary": local_days, "mobility_profile": self.car.to_dict(), "journey": plan["journey"]}, TripBudget(total_eur=500))
        self.assertGreater(summary["calculated_costs"]["local_transport"], local_only["calculated_costs"]["local_transport"])
        plan["destination"] = {"city": "Example", "country": "Latvia"}
        plan["budget_summary"] = summary
        plan["validation_context"] = {"travel_data": {"accommodations": [self.hotel], "activities": self.activities, "food_options": []}, "duration_days": 2, "mobility_profile": self.car.to_dict()}
        pdf = build_pdf_report(plan, {"traveller_count": 2})
        streams = []
        for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
            try:
                streams.append(zlib.decompress(base64.a85decode(stream.strip(), adobe=True)))
            except (ValueError, zlib.error):
                pass
        self.assertIn(b"Regional trip", b"\n".join(streams))

    def test_walking_and_unverified_routes_do_not_force_regional_trip(self):
        walking = MobilityProfile(preferred_transport="walking", allowed_transport_modes=("walking",))
        self.assertFalse(promote_regional_day(deepcopy(self.days), self.ranked, self.hotel, walking, TripConstraints(), self.strategy, RegionalRouter()))
        self.assertFalse(promote_regional_day(deepcopy(self.days), self.ranked, self.hotel, self.car, TripConstraints(), self.strategy, RegionalRouter(available=False)))

    def test_negative_category_is_not_promoted_even_with_verified_road(self):
        disliked = place("Regional museum", 24.405, "entertainment.museum")
        ranked = rank_places([self.near, self.local_two, self.regional, disliked], [IntentPreference("museum", "very_high", "negative")])
        days = deepcopy(self.days)
        self.assertFalse(promote_regional_day(days, ranked, self.hotel, self.car, TripConstraints(), TripStrategy.from_intents([]), RegionalRouter()))
        self.assertNotIn("Regional museum", [item["name"] for day in days for item in day["activities"]])

    def test_spatial_diversity_does_not_promote_unrouted_far_place(self):
        response = {"itinerary": deepcopy(self.days)}
        ranked = rank_places([self.near, self.local_two, self.regional], [])
        TravelRecommender._improve_spatial_diversity(response, ranked, [], self.car, self.hotel, RegionalRouter(available=False), TripConstraints())
        self.assertNotIn("Nature reserve", [item["name"] for day in response["itinerary"] for item in day["activities"]])

    def test_walking_and_public_transport_prefer_verified_local_alternatives(self):
        for profile in (MobilityProfile(preferred_transport="walking", allowed_transport_modes=("walking",)), MobilityProfile(preferred_transport="public_transport", allowed_transport_modes=("public_transport",))):
            days = [{"day": 1, "activities": [{"name": self.regional["name"]}]}]
            self.assertEqual(keep_selected_places_mobility_compatible(days, self.ranked, self.hotel, profile), 1)
            self.assertNotEqual(days[0]["activities"][0]["name"], self.regional["name"])

    def test_travel_cap_and_vehicle_availability_are_respected(self):
        self.assertFalse(promote_regional_day(deepcopy(self.days), self.ranked, self.hotel, self.car, TripConstraints(max_daily_travel_minutes=20), self.strategy, RegionalRouter()))
        no_car = MobilityProfile(preferred_transport="car", allowed_transport_modes=("car",), own_car=False, rental_car_allowed=False, driving_license=True)
        self.assertFalse(promote_regional_day(deepcopy(self.days), self.ranked, self.hotel, no_car, TripConstraints(), self.strategy, RegionalRouter()))

    def test_existing_regional_stop_gains_a_routed_companion(self):
        days = deepcopy(self.days)
        days[1]["activities"] = [{"name": self.regional["name"], "address": self.regional["address"], "reason": ""}]
        self.assertTrue(promote_regional_day(days, self.ranked, self.hotel, self.car, TripConstraints(), self.strategy, RegionalRouter()))
        self.assertEqual([item["name"] for item in days[1]["activities"]], [self.regional["name"], self.companion["name"]])

    def test_sparse_balanced_day_gets_local_companion_but_relaxed_day_does_not(self):
        days = deepcopy(self.days)
        count = fill_sparse_days(days, self.ranked, TripConstraints(), self.strategy, RegionalRouter(), MobilityProfile(preferred_transport="walking"))
        self.assertGreaterEqual(count, 1)
        relaxed = TripStrategy((), (), "relaxed")
        self.assertEqual(fill_sparse_days(deepcopy(self.days), self.ranked, TripConstraints(), relaxed, RegionalRouter(), self.car), 0)

    def test_removing_regional_stop_is_transactional_and_clears_claim(self):
        days = deepcopy(self.days)
        router = RegionalRouter()
        promote_regional_day(days, self.ranked, self.hotel, self.car, TripConstraints(max_daily_travel_minutes=90), self.strategy, router)
        DailyPlanner(router).plan(days, self.activities, self.intents, {}, {}, self.car, self.hotel, TripConstraints(max_daily_travel_minutes=90))
        plan = {"destination": {"city": "Example", "country": "Latvia"}, "selected_accommodation": self.hotel, "itinerary": days,
                "intent": [item.to_dict() for item in self.intents], "trip_constraints": TripConstraints(max_daily_travel_minutes=90).to_dict(),
                "trip_budget": TripBudget(total_eur=500).to_dict(), "mobility_profile": self.car.to_dict(),
                "validation_context": {"travel_data": {"accommodations": [self.hotel], "activities": self.activities, "food_options": []}, "duration_days": 2, "mobility_profile": self.car.to_dict()}}
        original = deepcopy(plan)
        edited = remove_activity(plan, 2, days[1]["activities"][0]["name"], {}, router)
        self.assertEqual(plan, original)
        self.assertEqual(len(edited["itinerary"][1]["activities"]), 1)
        self.assertNotIn("regional_trip", edited["itinerary"][1])
        self.assertEqual(len(itinerary_map_data(self.hotel, edited["itinerary"])["routes"][1]["coordinates"]), 3)

    def test_streamlit_results_render_regional_explanation_offline(self):
        days = deepcopy(self.days)
        router = RegionalRouter()
        promote_regional_day(days, self.ranked, self.hotel, self.car, TripConstraints(), self.strategy, router)
        DailyPlanner(router).plan(days, self.activities, self.intents, {}, {}, self.car, self.hotel)
        plan = {"destination": {"city": "Example", "country": "Latvia"}, "selected_accommodation": self.hotel, "itinerary": days,
                "trip_strategy": self.strategy.to_dict(), "mobility_profile": self.car.to_dict(),
                "validation_context": {"travel_data": {"accommodations": [self.hotel], "activities": self.activities, "food_options": []}, "duration_days": 2, "mobility_profile": self.car.to_dict()}}
        refresh_regional_explanations(plan)
        option = {"destination": "Example", "country": "Latvia", "short_description": "Sample test trip", "why_it_matches": "Nature", "estimated_total_budget": None, "duration_days": 2, "accommodation_type": "Hotel", "travel_style": "Comfortable", "main_activities": ["Nature"]}
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "src" / "main.py"))
        app.session_state["screen"] = "results"
        app.session_state["travel_plans"] = [option]
        app.session_state["selected_plan_index"] = 0
        app.session_state["travel_preferences"] = {"local_transport": "Own car"}
        app.session_state["real_recommendations_Example_Latvia"] = plan
        app.run(timeout=15)
        self.assertFalse(app.exception)
        self.assertTrue(any("Regional day trip" in element.value for element in app.info))


if __name__ == "__main__":
    unittest.main()
