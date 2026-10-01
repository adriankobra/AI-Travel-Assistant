"""LLM-based interpretation of traveler intent, separate from place discovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.ai.groq_client import GroqClient, GroqClientError


STRENGTHS = ("very_high", "high", "medium", "low")
POLARITIES = ("positive", "negative")

INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "preferences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept": {"type": "string"},
                    "strength": {"type": "string", "enum": list(STRENGTHS)},
                    "polarity": {"type": "string", "enum": list(POLARITIES)},
                },
                "required": ["concept", "strength", "polarity"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["preferences"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You interpret traveler preferences; you do not plan a trip.
Extract concise, reusable concepts from the supplied questionnaire data and natural-language note.
Keep both wanted and unwanted concepts. Strength means how strongly the traveler expressed it.
Use any clear concept needed by the user; do not force it into a fixed category list.
Write concepts in concise lower-case snake_case, such as near_the_sea or local_food.
Do not mention destinations, businesses, hotels, attractions, prices, availability, facilities,
or other factual claims. Return only the required JSON object."""


class IntentAnalysisError(ValueError):
    """Raised when user intent cannot be converted into a valid structured form."""


@dataclass(frozen=True)
class IntentPreference:
    concept: str
    strength: str
    polarity: str

    def to_dict(self) -> dict[str, str]:
        return {"concept": self.concept, "strength": self.strength, "polarity": self.polarity}


class IntentAnalyzer:
    """Use Groq only for language understanding, not for factual place claims."""

    def __init__(self, client: GroqClient | None = None) -> None:
        self._client = client or GroqClient()

    def analyze(self, preferences: dict[str, Any]) -> list[IntentPreference]:
        prompt = "Interpret this traveler preference data:\n" + json.dumps(
            self._relevant_preferences(preferences), ensure_ascii=False, default=str
        )
        try:
            response = self._client.send_structured_prompt(
                prompt, system_prompt=SYSTEM_PROMPT, response_schema=INTENT_SCHEMA
            )
        except GroqClientError as error:
            raise IntentAnalysisError(str(error)) from error
        return self._validate(response)

    @staticmethod
    def _relevant_preferences(preferences: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "additional_preferences", "notes", "trip_types", "travel_style", "accommodation",
            "hotel_category", "budget", "budget_scope", "duration", "custom_days",
            "travellers", "traveller_count", "travel_period",
            "trip_constraints",
            "budget_request",
            "origin", "destination_transport", "local_transport", "driving_license", "own_car",
            "rental_car_allowed", "rental_bicycle_allowed",
        )
        return {key: preferences.get(key) for key in keys if preferences.get(key) not in (None, "", [])}

    @staticmethod
    def _validate(response: dict[str, Any]) -> list[IntentPreference]:
        raw_preferences = response.get("preferences")
        if not isinstance(raw_preferences, list):
            raise IntentAnalysisError("Intent analysis returned an invalid preference list.")
        parsed: list[IntentPreference] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_preferences:
            if not isinstance(item, dict):
                raise IntentAnalysisError("Intent analysis returned an invalid preference.")
            concept = item.get("concept")
            strength = item.get("strength")
            polarity = item.get("polarity")
            if not isinstance(concept, str):
                raise IntentAnalysisError("Intent analysis returned an invalid concept.")
            if strength not in STRENGTHS or polarity not in POLARITIES:
                raise IntentAnalysisError("Intent analysis returned an invalid preference strength or polarity.")
            normalized_concept = IntentAnalyzer._normalise_concept(concept)
            if not normalized_concept:
                raise IntentAnalysisError("Intent analysis returned an invalid concept.")
            key = (normalized_concept, polarity)
            if key not in seen:
                parsed.append(IntentPreference(normalized_concept, strength, polarity))
                seen.add(key)
        return parsed

    @staticmethod
    def _normalise_concept(concept: str) -> str:
        """Accept safe multilingual LLM output while storing a stable identifier."""
        characters: list[str] = []
        for character in concept.casefold().strip().replace("&", " and "):
            characters.append(character if character.isalnum() else "_")
        normalized = "".join(characters).strip("_")
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        return normalized[:80]
