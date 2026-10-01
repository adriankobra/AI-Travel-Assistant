"""Offline tests for honest trip-budget behaviour."""
from __future__ import annotations
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from app.travel.budget import TripBudget, budget_summary, prefer_affordable


class BudgetTests(unittest.TestCase):
    def test_parses_total_people_and_excluded_flights(self):
        value = TripBudget.from_preferences({"budget_request": "I have a budget of 800 EUR for two people, excluding flights."})
        self.assertEqual((value.total_eur, value.people, value.flights_included), (800.0, 2, False))

    def test_parses_daily_budget(self):
        value = TripBudget.from_preferences({"budget_request": "We want to spend no more than 100 EUR per day."})
        self.assertEqual(value.daily_eur, 100.0)

    def test_unknown_prices_do_not_make_a_fake_total(self):
        plan = {"itinerary": [{"activities": [{"name": "Museum"}], "meals": []}], "selected_accommodation": {"name": "Hotel"}}
        summary = budget_summary(plan, TripBudget(total_eur=800))
        self.assertIsNone(summary["verified_total_eur"])
        self.assertEqual(summary["status"], "price data unavailable")

    def test_verified_prices_are_summed_only_with_source_and_unit(self):
        hotel = {"name": "Hotel", "price_eur": 100, "price_unit": "per_night", "price_data_status": "verified", "price_source": "test provider"}
        museum = {"name": "Museum", "price_eur": 20, "price_unit": "per_activity", "price_data_status": "verified", "price_source": "test provider"}
        plan = {"selected_accommodation": hotel, "itinerary": [{"activities": [museum], "meals": []}, {"activities": [], "meals": []}]}
        summary = budget_summary(plan, TripBudget(total_eur=250))
        self.assertEqual(summary["verified_total_eur"], 220.0)
        self.assertEqual(summary["status"], "partially verifiable")

    def test_affordable_verified_candidate_is_preferred_without_penalizing_unknown(self):
        expensive = {"name": "Expensive", "price_eur": 500, "price_unit": "per_activity", "price_data_status": "verified", "price_source": "test"}
        affordable = {"name": "Affordable", "price_eur": 50, "price_unit": "per_activity", "price_data_status": "verified", "price_source": "test"}
        unknown = {"name": "Unknown"}
        ordered = prefer_affordable([expensive, unknown, affordable], TripBudget(total_eur=100))
        self.assertEqual([item["name"] for item in ordered], ["Affordable", "Expensive", "Unknown"])
