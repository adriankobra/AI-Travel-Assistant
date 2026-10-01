"""Structured, explainable trip constraints extracted from user language."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class TripConstraints:
    max_daily_travel_minutes: int | None = None
    min_daily_free_minutes: int | None = None
    preferred_activity_count: int | None = None
    meal_duration_minutes: int | None = None
    preferred_start_minutes: int | None = None
    preferred_end_minutes: int | None = None
    requested_full_free_days: int | None = None

    @classmethod
    def from_preferences(cls, preferences: dict[str, Any]) -> "TripConstraints":
        text = " ".join(str(preferences.get(key, "")) for key in ("trip_constraints", "notes", "additional_preferences")).casefold()
        def duration(patterns: tuple[str, ...]) -> int | None:
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    value, unit = float(match.group(1)), match.group(2) if match.lastindex and match.lastindex >= 2 else "minutes"
                    return int(value * 60) if unit.startswith(("hour", "hr", "h")) else int(value)
            return None
        travel = duration((r"(?:no more than|maximum|max|under)\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\s+(?:of )?(?:travel|travelling|traveling)",))
        free = duration((r"(?:at least|minimum|min)\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\s+(?:of )?(?:free time|relaxation|rest)",))
        activities = re.search(r"(?:at most|maximum|max|prefer|around)\s+(\d+)\s+activities?(?:\s+per day)?", text)
        meals = duration((r"(?:meal|lunch|dinner)\s*(?:of|for)?\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)",))
        full_days = re.search(r"(\d+)\s+(?:full )?free days?", text)
        start = cls._clock(text, r"(?:start|wake up|begin)(?:\s+after)?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?")
        end = cls._clock(text, r"(?:end|finish|back)(?:\s+by| before)?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?")
        return cls(travel, free, int(activities.group(1)) if activities else None, meals, start, end, int(full_days.group(1)) if full_days else None)

    @staticmethod
    def _clock(text: str, pattern: str) -> int | None:
        match = re.search(pattern, text)
        if not match:
            return None
        hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3)
        if meridiem == "pm" and hour < 12: hour += 12
        if meridiem == "am" and hour == 12: hour = 0
        return hour * 60 + minute if 0 <= hour < 24 and 0 <= minute < 60 else None

    @classmethod
    def from_dict(cls, value: object) -> "TripConstraints":
        return cls(**{key: item for key, item in value.items() if key in cls.__dataclass_fields__}) if isinstance(value, dict) else cls()

    def to_dict(self) -> dict[str, int | None]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    def understood(self) -> list[str]:
        values = []
        if self.max_daily_travel_minutes is not None: values.append(f"Up to {self.max_daily_travel_minutes} min travel/day")
        if self.min_daily_free_minutes is not None: values.append(f"At least {self.min_daily_free_minutes} min free time/day")
        if self.preferred_activity_count is not None: values.append(f"Up to {self.preferred_activity_count} activities/day")
        if self.meal_duration_minutes is not None: values.append(f"{self.meal_duration_minutes} min meal allowance")
        if self.preferred_start_minutes is not None: values.append(f"Start after {self.preferred_start_minutes // 60:02d}:{self.preferred_start_minutes % 60:02d}")
        if self.preferred_end_minutes is not None: values.append(f"End by {self.preferred_end_minutes // 60:02d}:{self.preferred_end_minutes % 60:02d}")
        if self.requested_full_free_days is not None: values.append(f"{self.requested_full_free_days} requested full free day(s)")
        return values


def assess_plan_fit(plan: dict[str, Any], constraints: TripConstraints) -> list[dict[str, str]]:
    """Return factual status, never convert unknown route facts into a score."""
    result: list[dict[str, str]] = []
    days = [day for day in plan.get("itinerary", []) if isinstance(day, dict)]
    if constraints.preferred_start_minutes is not None:
        starts = [day.get("schedule", {}).get("day_start_minutes") for day in days]
        if all(isinstance(value, int) for value in starts):
            status = "satisfied" if all(value >= constraints.preferred_start_minutes for value in starts) else "partially satisfied"
        else:
            status = "unavailable to verify"
        result.append({"constraint": "Preferred start time", "status": status})
    if constraints.preferred_end_minutes is not None:
        ends: list[int] = []
        for day in days:
            entries = [*day.get("activities", []), *day.get("meals", [])]
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("end_time"), str):
                    continue
                try:
                    hour, minute = entry["end_time"].split(":")
                    ends.append(int(hour) * 60 + int(minute))
                except (TypeError, ValueError):
                    continue
        status = "unavailable to verify" if not ends else ("satisfied" if max(ends) <= constraints.preferred_end_minutes else "partially satisfied")
        result.append({"constraint": "Preferred end time", "status": status})
    if constraints.meal_duration_minutes is not None:
        meals = [meal for day in days for meal in day.get("meals", []) if isinstance(meal, dict)]
        if not meals or not all(isinstance(meal.get("duration_minutes"), int) for meal in meals):
            status = "unavailable to verify"
        else:
            status = "satisfied" if all(meal["duration_minutes"] >= constraints.meal_duration_minutes for meal in meals) else "partially satisfied"
        result.append({"constraint": "Meal duration", "status": status})
    if constraints.min_daily_free_minutes is not None:
        ok = all(isinstance(day.get("schedule", {}).get("free_time_minutes"), int) and day["schedule"]["free_time_minutes"] >= constraints.min_daily_free_minutes for day in days)
        result.append({"constraint": "Daily free time", "status": "satisfied" if ok else "partially satisfied"})
    if constraints.preferred_activity_count is not None:
        ok = all(len(day.get("activities", [])) <= constraints.preferred_activity_count for day in days)
        result.append({"constraint": "Activities per day", "status": "satisfied" if ok else "partially satisfied"})
    if constraints.max_daily_travel_minutes is not None:
        statuses = []
        for day in days:
            travel = [item for item in day.get("items", []) if isinstance(item, dict) and item.get("item_type") == "travel"]
            return_route = day.get("return_route")
            if any(item.get("travel_time_data_status") != "verified" or item.get("requested_transport_mode") == "motorcycle" for item in travel) or (day.get("activities") and (not isinstance(return_route, dict) or return_route.get("data_status") != "verified" or return_route.get("duration_minutes") is None or day.get("schedule", {}).get("planned_transport_mode") == "motorcycle")):
                statuses.append(None)
            else:
                minutes = sum(int(item.get("travel_duration_minutes", 0)) for item in travel)
                if isinstance(return_route, dict) and return_route.get("data_status") == "verified":
                    minutes += int(return_route.get("duration_minutes") or 0)
                statuses.append(minutes <= constraints.max_daily_travel_minutes)
        status = "unavailable to verify" if any(value is None for value in statuses) else ("satisfied" if all(statuses) else "partially satisfied")
        result.append({"constraint": "Daily travel time", "status": status})
    if constraints.requested_full_free_days:
        result.append({"constraint": "Full free days", "status": "unavailable to verify"})
    return result
