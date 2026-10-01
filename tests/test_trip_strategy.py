from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.intent_analyzer import IntentPreference
from app.travel.trip_strategy import TripStrategy


class TripStrategyTests(unittest.TestCase):
    def test_preserves_priorities_avoidances_and_relaxed_free_time_explanation(self) -> None:
        strategy = TripStrategy.from_intents([
            IntentPreference("wellness", "very_high", "positive"),
            IntentPreference("romantic", "high", "positive"),
            IntentPreference("museum", "high", "negative"),
        ])
        self.assertEqual(strategy.pace, "relaxed")
        self.assertEqual(strategy.primary_concepts[0], "wellness")
        self.assertEqual(strategy.avoided_concepts, ("museum",))
        self.assertIn("wellness", strategy.day_explanation(["wellness"], 120))

    def test_active_preferences_produce_active_strategy_without_place_claims(self) -> None:
        strategy = TripStrategy.from_intents([IntentPreference("adventure", "high", "positive")])
        self.assertEqual(strategy.pace, "active")


if __name__ == "__main__":
    unittest.main()
