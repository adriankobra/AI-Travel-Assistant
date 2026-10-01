"""Honest budget parsing and verified-cost reporting.

Geoapify currently supplies place identity and location, not dependable prices.
This module therefore accepts only explicitly sourced, verified price records
and never estimates a missing cost from a category, city, or LLM response.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from app.travel.transport_planning import local_fuel_cost


@dataclass(frozen=True)
class TripBudget:
    total_eur: float | None = None
    daily_eur: float | None = None
    people: int | None = None
    flights_included: bool | None = None

    @classmethod
    def from_preferences(cls, preferences: dict[str, Any]) -> "TripBudget":
        text = " ".join(str(preferences.get(key, "")) for key in ("budget_request", "notes")).casefold()
        total_match = re.search(r"(?:budget\s+(?:of|is)|have\s+(?:a\s+)?budget\s+of|(?:spend|no more than|maximum|max)\s+)€?\s*(\d+(?:[.,]\d+)?)\s*(?:eur|euro|€)?(?!\s*(?:a|per)\s*day)", text)
        if total_match is None:
            request = str(preferences.get("budget_request", "")).casefold().strip()
            total_match = re.match(r"(?:€\s*)?(\d+(?:[.,]\d+)?)\s*(?:eur|euro|€)?(?:\s|$)", request) if "per day" not in request and "a day" not in request else None
        daily_match = re.search(r"(?:€?\s*(\d+(?:[.,]\d+)?)\s*(?:eur|euro|€)?\s*(?:a|per)\s*day)", text)
        people_match = re.search(r"(?:for|between)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:people|persons|travellers|travelers)", text)
        total = float(total_match.group(1).replace(",", ".")) if total_match else None
        daily = float(daily_match.group(1).replace(",", ".")) if daily_match else None
        people_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
        people = (int(people_match.group(1)) if people_match and people_match.group(1).isdigit() else people_words.get(people_match.group(1)) if people_match else None)
        flights_included: bool | None = False if "excluding flights" in text or "without flights" in text else (True if "including flights" in text else None)
        return cls(total, daily, people, flights_included)

    @classmethod
    def from_dict(cls, value: object) -> "TripBudget":
        return cls(**{key: item for key, item in value.items() if key in cls.__dataclass_fields__}) if isinstance(value, dict) else cls()

    def to_dict(self) -> dict[str, float | int | bool | None]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    def understood(self) -> str:
        parts: list[str] = []
        if self.total_eur is not None:
            parts.append(f"€{self.total_eur:g} total")
        if self.daily_eur is not None:
            parts.append(f"€{self.daily_eur:g}/day")
        if self.people is not None:
            parts.append(f"{self.people} people")
        if self.flights_included is False:
            parts.append("flights excluded")
        elif self.flights_included is True:
            parts.append("flights included")
        return " / ".join(parts)


def verified_price(place: object, *, nights: int = 1) -> float | None:
    """Return a cost only for an explicit provider-backed price record."""
    if not isinstance(place, dict) or place.get("price_data_status") != "verified" or not place.get("price_source"):
        return None
    value = place.get("price_eur")
    unit = place.get("price_unit")
    if not isinstance(value, (int, float)) or value < 0:
        return None
    if unit == "per_night":
        return float(value) * max(nights, 1)
    if unit in {"trip_total", "per_activity", "per_meal"}:
        return float(value)
    return None


def budget_summary(plan: dict[str, Any], budget: TripBudget) -> dict[str, Any]:
    """Summarise only verified costs and name every unknown category."""
    nights = max(len(plan.get("itinerary", [])), 1)
    accommodation = verified_price(plan.get("selected_accommodation"), nights=nights)
    activities = [verified_price(activity) for day in plan.get("itinerary", []) if isinstance(day, dict) for activity in day.get("activities", []) if isinstance(activity, dict)]
    # A meal displays alternatives; only its first option is the current one.
    food = [verified_price(meal["options"][0]) for day in plan.get("itinerary", []) if isinstance(day, dict) for meal in day.get("meals", []) if isinstance(meal, dict) and isinstance(meal.get("options"), list) and meal["options"] and isinstance(meal["options"][0], dict)]
    costs = {
        "transport_to_destination": None,
        "accommodation": accommodation,
        "activities": sum(value for value in activities if value is not None) if activities and all(value is not None for value in activities) else None,
        "food": sum(value for value in food if value is not None) if food and all(value is not None for value in food) else None,
        "local_transport": None,
        "return_journey": None,
    }
    journey = plan.get("journey", {})
    if not isinstance(journey, dict):
        journey = {}
    outbound = journey.get("outbound", {})
    returning = journey.get("return", {})
    local = local_fuel_cost(plan, journey)
    calculated = {
        "transport_to_destination": outbound.get("fuel_cost_eur") if isinstance(outbound, dict) else None,
        "return_journey": returning.get("fuel_cost_eur") if isinstance(returning, dict) else None,
        "local_transport": local.get("cost_eur"),
    }
    has_calculated = any(isinstance(value, (int, float)) for value in calculated.values())
    known = [value for value in costs.values() if value is not None]
    unknown = [name for name, value in costs.items() if value is None and calculated.get(name) is None]
    # This is a subtotal of provider-verified records, never a claimed trip
    # total when other categories have no price data.
    total = sum(known) if known else None
    target = budget.total_eur
    if target is None and budget.daily_eur is not None:
        target = budget.daily_eur * nights
    if target is None:
        status = "price data unavailable" if not known and not has_calculated else "partially verifiable"
    elif total is None:
        status = "partially verifiable" if has_calculated else "price data unavailable"
    elif unknown or has_calculated:
        status = "partially verifiable"
    else:
        status = "within verified budget data" if total <= target else "over verified budget data"
    return {
        "budget": budget.to_dict(), "verified_costs": costs,
        "calculated_costs": calculated,
        "calculation_note": "Fuel amounts are estimates from verified ORS road distance and user inputs; they exclude tolls, parking, vehicle rental and other unknown costs.",
        "local_distance_status": local.get("status"),
        "verified_total_eur": total,
        "accounted_subtotal_eur": round(sum(known) + sum(float(value) for value in calculated.values() if isinstance(value, (int, float))), 2) if known or has_calculated else None,
        "unknown_categories": unknown, "status": status,
    }


def prefer_affordable(places: Iterable[dict[str, Any]], budget: TripBudget, *, nights: int = 1) -> list[dict[str, Any]]:
    """Stable preference for a known affordable option; unknown prices stay neutral."""
    limit = budget.total_eur if budget.total_eur is not None else budget.daily_eur
    values = list(places)
    if limit is None:
        return values
    affordable = [place for place in values if (cost := verified_price(place, nights=nights)) is not None and cost <= limit]
    return affordable + [place for place in values if place not in affordable]
