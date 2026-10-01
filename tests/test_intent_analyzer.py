"""Offline contract tests for broad natural-language intent interpretation."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.intent_analyzer import IntentAnalyzer, IntentAnalysisError


class StubGroqClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.prompt = ""

    def send_structured_prompt(self, prompt: str, **_: object) -> dict:
        self.prompt = prompt
        return self.response


class IntentAnalyzerTests(unittest.TestCase):
    def test_keeps_positive_negative_strength_and_unknown_concepts(self) -> None:
        client = StubGroqClient({"preferences": [
            {"concept": "relaxation", "strength": "very_high", "polarity": "positive"},
            {"concept": "walking", "strength": "high", "polarity": "negative"},
            {"concept": "jet ski rental", "strength": "high", "polarity": "positive"},
            {"concept": "Beach & Relaxation", "strength": "high", "polarity": "positive"},
        ]})
        intents = IntentAnalyzer(client=client).analyze({"notes": "I want a spa, no walking, and jet ski rental."})
        self.assertEqual(
            [intent.concept for intent in intents],
            ["relaxation", "walking", "jet_ski_rental", "beach_and_relaxation"],
        )
        self.assertEqual(intents[1].polarity, "negative")
        self.assertIn("jet ski rental", client.prompt)

    def test_preserves_different_natural_language_requests_in_the_llm_input(self) -> None:
        examples = [
            "I love relaxing and want SPA.", "I want to walk around the city all day.",
            "I do not want much walking.", "I want to rent a bicycle.",
            "I want to rent a car.", "I want something romantic.", "I want nightlife.",
            "I want nature and hiking.", "I want good local food.", "I hate museums.",
            "I want swimming and water activities.", "I just want to relax and do almost nothing.",
            "I want a mix of sightseeing and relaxation.", "I want activities for children.",
        ]
        for note in examples:
            with self.subTest(note=note):
                client = StubGroqClient({"preferences": []})
                IntentAnalyzer(client=client).analyze({"notes": note})
                self.assertIn(note, client.prompt)

    def test_rejects_invalid_llm_intent(self) -> None:
        client = StubGroqClient({"preferences": [{"concept": "spa", "strength": "urgent", "polarity": "positive"}]})
        with self.assertRaises(IntentAnalysisError):
            IntentAnalyzer(client=client).analyze({"notes": "spa"})

    def test_preserves_budget_request_with_other_user_language(self) -> None:
        client = StubGroqClient({"preferences": []})
        IntentAnalyzer(client=client).analyze({"notes": "I want local food", "budget_request": "€100 per day"})
        self.assertIn("budget_request", client.prompt)
        self.assertIn("€100 per day", client.prompt)
