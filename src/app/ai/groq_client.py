"""Small, reusable wrapper around the Groq chat-completions API.

This module deliberately has no Streamlit imports.  The UI can use it, but later
agent and service layers can use exactly the same client too.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = "openai/gpt-oss-20b"


class GroqClientError(Exception):
    """Base error for a user-safe Groq client failure."""


class GroqConfigurationError(GroqClientError):
    """Raised when the required local configuration is missing."""


class GroqRequestError(GroqClientError):
    """Raised when Groq cannot complete a request."""


class GroqEmptyResponseError(GroqClientError):
    """Raised when Groq returns no usable assistant content."""


class GroqClient:
    """Send text or JSON-object requests through a configured Groq model."""

    def __init__(self, model: str | None = None) -> None:
        # An explicit path means this works regardless of the command's cwd.
        load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise GroqConfigurationError(
                "GROQ_API_KEY is missing. Add it to the project's .env file and restart Streamlit."
            )

        self.model = model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)
        self._client = Groq(api_key=api_key)

    def send_prompt(self, prompt: str, *, system_prompt: str | None = None) -> str:
        """Return plain text from the configured model."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self._complete(messages)

    def send_structured_prompt(
        self,
        prompt: str,
        *,
        system_prompt: str = "Reply with one valid JSON object only.",
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Request a JSON object, optionally constrained by a Groq JSON schema."""
        response_format: dict[str, Any] = {"type": "json_object"}
        if response_schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "travel_plan_response",
                    "strict": True,
                    "schema": response_schema,
                },
            }
        content = self._complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            response_format=response_format,
        )
        try:
            result = json.loads(content)
        except json.JSONDecodeError as error:
            raise GroqRequestError("Groq returned an invalid JSON response. Please try again.") from error
        if not isinstance(result, dict):
            raise GroqRequestError("Groq returned JSON, but not the expected object. Please try again.")
        return result

    def _complete(
        self, messages: list[dict[str, str]], *, response_format: dict[str, Any] | None = None
    ) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=0,
                max_completion_tokens=8000,
                response_format=response_format,  # type: ignore[arg-type]
            )
        except Exception as error:
            raise GroqRequestError(
                f"Groq request failed: {type(error).__name__}: {error}"
            ) from error

        content = response.choices[0].message.content if response.choices else None
        if not content or not content.strip():
            raise GroqEmptyResponseError("Groq returned an empty response. Please try again.")
        return content.strip()


def test_groq_connection() -> dict[str, Any]:
    """Perform the small Phase 2 structured request used by the temporary UI check."""
    client = GroqClient()
    return client.send_structured_prompt(
        "Return a JSON object with exactly these fields: "
        '"service" set to "Groq", "connection" set to "successful", and "message" as a short greeting.'
    )
