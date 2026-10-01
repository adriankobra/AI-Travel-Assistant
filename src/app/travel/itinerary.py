"""Small helpers for the structured, dictionary-compatible itinerary contract."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


PLACE_FIELDS = ("name", "address", "latitude", "longitude", "place_id", "categories", "type", "datasource")


def place_snapshot(place: dict[str, Any] | None) -> dict[str, Any]:
    """Copy only factual Geoapify fields into a timeline item."""
    if not isinstance(place, dict):
        return {}
    return {field: place[field] for field in PLACE_FIELDS if field in place}


def day_date(preferences: dict[str, Any], day_number: int) -> str | None:
    """Expose a date only when the questionnaire supplied a concrete start date."""
    dates = preferences.get("dates")
    if not isinstance(dates, (list, tuple)) or not dates:
        return None
    start = dates[0]
    if isinstance(start, date):
        return (start + timedelta(days=day_number - 1)).isoformat()
    return str(start) if isinstance(start, str) and start else None


def timeline_item(item_type: str, *, start_time: str | None = None, end_time: str | None = None, duration_minutes: int | None = None, source: str | None = None, **fields: Any) -> dict[str, Any]:
    """Create an explicit itinerary item without requiring callers to use a class."""
    item: dict[str, Any] = {"item_type": item_type}
    if start_time is not None:
        item["start_time"] = start_time
    if end_time is not None:
        item["end_time"] = end_time
    if duration_minutes is not None:
        item["duration_minutes"] = duration_minutes
    if source is not None:
        item["source"] = source
    item.update({key: value for key, value in fields.items() if value is not None})
    return item
