"""Regression tests for the strict structured mobility response contract."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.mobility_analyzer import MOBILITY_SCHEMA, MobilityAnalyzer


class CapturingClient:
    def __init__(self, response: dict | None = None) -> None:
        self.system_prompt = ""
        self.schema: dict = {}
        self.response = response

    def send_structured_prompt(self, _prompt: str, **kwargs: object) -> dict:
        self.system_prompt = str(kwargs["system_prompt"])
        self.schema = dict(kwargs["response_schema"])
        return self.response if self.response is not None else {field: None for field in self.schema["required"]}


class MobilityAnalyzerTests(unittest.TestCase):
    def test_unknown_values_are_allowed_by_schema_and_preserved(self) -> None:
        client = CapturingClient()
        profile = MobilityAnalyzer(client=client).analyze({"additional_preferences": "Near the sea"})

        self.assertEqual(client.schema, MOBILITY_SCHEMA)
        self.assertEqual(MOBILITY_SCHEMA["properties"]["mixed_strategy"]["type"], ["boolean", "null"])

    def test_literal_null_transport_is_normalized_as_unknown(self):
        client = CapturingClient({
            "preferred_transport": "null",
            "allowed_transport_modes": None,
            "driving_license": None,
            "own_car": None,
            "rental_car_allowed": None,
            "rental_bicycle_allowed": None,
            "walking_preference": None,
            "public_transport_preference": None,
            "bicycle_preference": None,
            "motorcycle_preference": None,
            "car_usage": None,
            "public_transport_usage": None,
            "mixed_strategy": None,
            "city_transport": None,
            "outside_city_transport": "null",
        })

        profile = MobilityAnalyzer(client=client).analyze({})

        self.assertIsNone(profile.preferred_transport)
        self.assertIsNone(profile.outside_city_transport)
        self.assertIsNone(profile.mixed_strategy)
        self.assertIsNone(profile.driving_license)

    def test_prompt_requires_null_for_unknown_mobility(self) -> None:
        client = CapturingClient()
        MobilityAnalyzer(client=client).analyze({})

        self.assertIn("Use null for every unknown field", client.system_prompt)
        self.assertIn("never infer false", client.system_prompt)


if __name__ == "__main__":
    unittest.main()
