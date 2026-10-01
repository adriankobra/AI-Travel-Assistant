"""A transparent whole-trip strategy derived from existing structured intent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.ai.intent_analyzer import IntentPreference


_WEIGHTS = {"very_high": 4, "high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True)
class TripStrategy:
    """Planning priorities, not claims about places or destination facts."""

    primary_concepts: tuple[str, ...]
    avoided_concepts: tuple[str, ...]
    pace: str

    @classmethod
    def from_intents(cls, intents: Iterable[IntentPreference]) -> "TripStrategy":
        values = list(intents)
        positive = sorted(
            (item for item in values if item.polarity == "positive"),
            key=lambda item: (-_WEIGHTS[item.strength], item.concept),
        )
        negative = sorted(
            (item for item in values if item.polarity == "negative"),
            key=lambda item: (-_WEIGHTS[item.strength], item.concept),
        )
        concepts = {item.concept for item in positive}
        # Pace describes the plan's planning posture only.  It does not assert
        # that any specific place offers a facility or experience.
        relaxed = any(token in concept for concept in concepts for token in ("relax", "slow", "wellness", "spa", "beach"))
        active = any(token in concept for concept in concepts for token in ("active", "adventure", "hiking", "explor", "walking"))
        pace = "balanced" if relaxed == active else "relaxed" if relaxed else "active"
        return cls(tuple(item.concept for item in positive[:6]), tuple(item.concept for item in negative[:6]), pace)

    def to_dict(self) -> dict[str, Any]:
        return {"primary_concepts": list(self.primary_concepts), "avoided_concepts": list(self.avoided_concepts), "pace": self.pace}

    def day_explanation(self, matched_concepts: Iterable[str], free_time_minutes: object) -> str:
        matched = list(dict.fromkeys(value for value in matched_concepts if value in self.primary_concepts))
        if matched:
            text = "Planned around verified category matches for " + ", ".join(value.replace("_", " ") for value in matched) + "."
        else:
            text = "Planned from verified places to balance the trip across its available activities."
        if self.pace == "relaxed" and isinstance(free_time_minutes, int) and free_time_minutes > 0:
            text += " Free time is deliberately retained for the requested relaxed pace."
        return text
