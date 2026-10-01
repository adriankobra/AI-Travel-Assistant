"""
AI service for generating travel destination options.

This agent only creates destination-level ideas.
Real places and detailed itineraries are handled later.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.groq_client import GroqClient, GroqClientError


class TravelAgentError(Exception):
    """Friendly error for the Streamlit UI."""


TRAVEL_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "trips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "string"
                    },
                    "country": {
                        "type": "string"
                    },
                    "short_description": {
                        "type": "string"
                    },
                    "why_it_matches": {
                        "type": "string"
                    },
                    "estimated_total_budget": {
                        "type": ["number", "null"]
                    },
                    "duration_days": {
                        "type": "integer"
                    },
                    "accommodation_type": {
                        "type": "string"
                    },
                    "travel_style": {
                        "type": "string"
                    },
                    "main_activities": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    }
                },
                "required": [
                    "destination",
                    "country",
                    "short_description",
                    "why_it_matches",
                    "estimated_total_budget",
                    "duration_days",
                    "accommodation_type",
                    "travel_style",
                    "main_activities"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": [
        "trips"
    ],
    "additionalProperties": False
}


SYSTEM_PROMPT = (
    "Generate exactly five distinct destination options. Keep each destination in a supplied country. "
    "Consider the stated origin and preferred journey mode when choosing destinations, but do not claim a route, service, travel time, or fare has been verified. "
    "Use general activity types only, never business names. This application has no verified destination-price provider, so return null for estimated_total_budget. "
    "Return only the strict schema JSON."
)


class TravelAgent:

    def __init__(
        self,
        client: GroqClient | None = None
    ) -> None:

        self._client = client or GroqClient()

    def generate_options(
        self,
        preferences: dict[str, Any]
    ) -> list[dict[str, Any]]:

        # Get selected values from questionnaire.
        countries = preferences.get(
            "countries",
            []
        )

        if not countries:
            other_country = preferences.get(
                "other_country"
            )

            if other_country:
                countries = [
                    other_country
                ]

        trip_type = preferences.get(
            "trip_types",
            []
        )

        travel_style = preferences.get(
            "travel_style",
            ""
        )

        budget = preferences.get(
            "budget",
            ""
        )

        duration = preferences.get(
            "duration",
            ""
        )

        accommodation = preferences.get(
            "accommodation",
            ""
        )

        travellers = preferences.get(
            "travellers",
            1
        )

        additional_preferences = preferences.get(
            "additional_preferences",
            ""
        )

        # GPT-OSS strict structured output accepts this schema, but its
        # constrained decoder can reject the older prose-heavy field/value
        # prompt with ``json_validate_failed``. Keep the same preference data,
        # but present it as one unambiguous JSON object rather than interleaved
        # labels, values, and instructions.
        prompt_preferences = {
            "countries": countries if countries else None,
            "trip_types": trip_type if trip_type else None,
            "travel_style": travel_style or None,
            "budget": budget or None,
            "duration": duration or None,
            "accommodation": accommodation or None,
            "travellers": travellers,
            "additional_preferences": additional_preferences or None,
            "origin": preferences.get("origin") or None,
            "destination_transport": preferences.get("destination_transport") or None,
            "journey_vehicle": preferences.get("journey_vehicle") or None,
            "local_transport": preferences.get("local_transport") or None,
        }
        prompt = json.dumps(
            {"task": "five destination options; no detailed itinerary", "preferences": prompt_preferences},
            ensure_ascii=False,
            default=str,
        )

        try:

            response = self._client.send_structured_prompt(
                prompt,
                system_prompt=SYSTEM_PROMPT,
                response_schema=TRAVEL_PLAN_SCHEMA,
            )

        except GroqClientError as error:

            raise TravelAgentError(
                str(error)
            ) from error

        return self._validate_options(
            response
        )

    @staticmethod
    def _validate_options(
        response: dict[str, Any]
    ) -> list[dict[str, Any]]:

        trips = response.get(
            "trips"
        )

        if not isinstance(
            trips,
            list
        ):

            raise TravelAgentError(
                "The AI did not return valid travel options."
            )

        if len(trips) != 5:

            raise TravelAgentError(
                "The AI did not return five travel options."
            )

        required_fields = {
            "destination",
            "country",
            "short_description",
            "why_it_matches",
            "estimated_total_budget",
            "duration_days",
            "accommodation_type",
            "travel_style",
            "main_activities",
        }

        for number, trip in enumerate(
            trips,
            start=1
        ):

            if not isinstance(
                trip,
                dict
            ):

                raise TravelAgentError(
                    f"Travel option {number} is invalid."
                )

            if not required_fields.issubset(
                trip.keys()
            ):

                raise TravelAgentError(
                    f"Travel option {number} "
                    "is missing information."
                )

            if not isinstance(
                trip["duration_days"],
                int
            ):

                raise TravelAgentError(
                    f"Travel option {number} "
                    "has an invalid duration."
                )

            if trip["estimated_total_budget"] is not None and not isinstance(
                trip["estimated_total_budget"],
                (int, float)
            ):

                raise TravelAgentError(
                    f"Travel option {number} "
                    "has an invalid budget."
                )

            if not isinstance(
                trip["main_activities"],
                list
            ):

                raise TravelAgentError(
                    f"Travel option {number} "
                    "has invalid activities."
                )

        return trips
