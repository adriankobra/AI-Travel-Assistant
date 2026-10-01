"""Regression test for questionnaire preference names passed to TravelAgent."""

from __future__ import annotations

import sys
import json
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.travel_agent import TravelAgent


class CapturingClient:
    """Offline Groq substitute that records the prompt and returns valid options."""

    def __init__(self) -> None:
        self.prompt = ""

    def send_structured_prompt(self, prompt: str, **_: object) -> dict:
        self.prompt = prompt
        option = {
            "destination": "Pärnu", "country": "Estonia", "short_description": "Coastal city",
            "why_it_matches": "Beach and food", "estimated_total_budget": 500,
            "duration_days": 3, "accommodation_type": "Hotel", "travel_style": "Budget",
            "main_activities": ["beach", "food", "culture"],
        }
        return {"trips": [option.copy() for _ in range(5)]}


class TravelAgentPreferenceTests(unittest.TestCase):
    def test_uses_questionnaire_trip_types_key(self) -> None:
        client = CapturingClient()
        TravelAgent(client=client).generate_options({"countries": ["Estonia"], "trip_types": ["Beach & Relaxation"]})
        self.assertIn("Beach & Relaxation", client.prompt)

    def test_serializes_preferences_as_one_json_object_for_strict_output(self) -> None:
        client = CapturingClient()
        TravelAgent(client=client).generate_options({
            "countries": ["Estonia"], "trip_types": ["Beach & Relaxation"],
            "travel_style": "Relaxed", "budget": "€500–€800", "duration": "3–5 days",
            "accommodation": "Hotel", "travellers": "Couple", "additional_preferences": "Near the sea",
        })
        payload = json.loads(client.prompt)
        self.assertEqual(payload["preferences"]["countries"], ["Estonia"])
        self.assertEqual(payload["preferences"]["trip_types"], ["Beach & Relaxation"])


if __name__ == "__main__":
    unittest.main()
