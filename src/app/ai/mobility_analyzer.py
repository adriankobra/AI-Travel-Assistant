"""LLM extraction of a structured mobility profile without transport assumptions."""

from __future__ import annotations

import json
from typing import Any

from app.ai.groq_client import GroqClient, GroqClientError
from app.travel.mobility import MobilityProfile, PREFERENCE_STRENGTHS, TRANSPORT_MODES


def _nullable_string_enum(values: tuple[str, ...]) -> dict[str, Any]:
    # GPT-OSS occasionally serializes an unknown enum as the literal string
    # ``"null"`` despite being instructed to emit JSON null.  Accept that
    # one representation at the response boundary; ``MobilityProfile``
    # deliberately normalizes it back to ``None`` and never treats it as a
    # transport mode.
    return {"type": ["string", "null"], "enum": [*values, None, "null"]}


MOBILITY_SCHEMA: dict[str, Any] = {
    "type": "object", "properties": {
        "preferred_transport": _nullable_string_enum(TRANSPORT_MODES),
        "allowed_transport_modes": {"type": ["array", "null"], "items": {"type": "string", "enum": list(TRANSPORT_MODES)}},
        "driving_license": {"type": ["boolean", "null"]}, "own_car": {"type": ["boolean", "null"]},
        "rental_car_allowed": {"type": ["boolean", "null"]}, "rental_bicycle_allowed": {"type": ["boolean", "null"]},
        "walking_preference": _nullable_string_enum(PREFERENCE_STRENGTHS),
        "public_transport_preference": _nullable_string_enum(PREFERENCE_STRENGTHS),
        "bicycle_preference": _nullable_string_enum(PREFERENCE_STRENGTHS),
        "motorcycle_preference": _nullable_string_enum(PREFERENCE_STRENGTHS),
        "car_usage": {"type": ["boolean", "null"]}, "public_transport_usage": {"type": ["boolean", "null"]},
        "mixed_strategy": {"type": ["boolean", "null"]}, "city_transport": _nullable_string_enum(TRANSPORT_MODES),
        "outside_city_transport": _nullable_string_enum(TRANSPORT_MODES),
    },
    "required": ["preferred_transport", "allowed_transport_modes", "driving_license", "own_car", "rental_car_allowed", "rental_bicycle_allowed", "walking_preference", "public_transport_preference", "bicycle_preference", "motorcycle_preference", "car_usage", "public_transport_usage", "mixed_strategy", "city_transport", "outside_city_transport"],
    "additionalProperties": False,
}


class MobilityAnalyzer:
    def __init__(self, client: GroqClient | None = None) -> None:
        self.client = client or GroqClient()

    def analyze(self, preferences: dict[str, Any]) -> MobilityProfile:
        relevant = {key: preferences[key] for key in ("additional_preferences", "notes", "trip_types", "travel_style", "local_transport", "driving_license", "own_car", "rental_car_allowed", "rental_bicycle_allowed") if preferences.get(key) not in (None, "", [])}
        try:
            result = self.client.send_structured_prompt(
                "Extract transportation capability, availability and preference from this travel data. Unknown means null; never infer it.\n" + json.dumps(relevant, ensure_ascii=False),
                system_prompt=("You extract a mobility profile, not places or routes. Keep capability (license), availability (own/rental car), and preference separate. "
                               "Use true only for an explicit yes, preference, capability, or permission, and false only for an explicit no, dislike, or disallowance. "
                               "Use null for every unknown field; never infer false from omitted information, a driving preference from a license, or usage from ownership. "
                               "For only-walking requests set allowed_transport_modes to [walking], car_usage false, and public_transport_usage false unless explicitly allowed. "
                               "Set mixed_strategy true only when different city and outside-city transport choices are explicitly stated; otherwise use null unless it is explicitly false. Return only JSON."),
                response_schema=MOBILITY_SCHEMA,
            )
        except GroqClientError as error:
            raise ValueError(f"Mobility analysis failed: {error}") from error
        return self._apply_explicit_questionnaire_signals(MobilityProfile.from_dict(result), preferences)

    @staticmethod
    def _apply_explicit_questionnaire_signals(profile: MobilityProfile, preferences: dict[str, Any]) -> MobilityProfile:
        """Use explicit questionnaire choices, never guessed capability, for routing."""
        values = " ".join(str(value).casefold() for value in preferences.get("additional_preferences", []) if isinstance(value, str))
        data = profile.to_dict()
        local = str(preferences.get("local_transport", "")).casefold()
        explicit = {
            "walking / mostly walking": "walking", "public transport": "public_transport",
            "own car": "car", "rental car": "car", "bicycle": "bicycle", "motorcycle": "motorcycle",
        }.get(local)
        if explicit:
            data["preferred_transport"] = explicit
            data["allowed_transport_modes"] = [explicit]
        elif local == "mixed transport":
            data["mixed_strategy"] = True
            data["preferred_transport"] = "walking"
            available = ["walking", "public_transport"]
            if preferences.get("driving_license") and (preferences.get("own_car") or preferences.get("rental_car_allowed")):
                available.append("car")
            if preferences.get("rental_bicycle_allowed"):
                available.append("bicycle")
            data["allowed_transport_modes"] = available
        for field in ("driving_license", "own_car", "rental_car_allowed", "rental_bicycle_allowed"):
            if isinstance(preferences.get(field), bool):
                data[field] = preferences[field]
        if local == "own car": data["own_car"], data["car_usage"] = True, True
        if local == "rental car": data["rental_car_allowed"], data["car_usage"] = True, True
        if local == "motorcycle": data["motorcycle_preference"] = "very_high"
        if local == "bicycle": data["bicycle_preference"] = "very_high"
        if local == "public transport": data["public_transport_usage"] = True
        if "road trip" in values and not explicit:
            data["preferred_transport"] = data["preferred_transport"] or "car"
            data["car_usage"] = True if data["car_usage"] is None else data["car_usage"]
        return MobilityProfile.from_dict(data)
