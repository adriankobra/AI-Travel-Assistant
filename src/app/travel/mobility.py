"""Transport capability, availability and preference kept separate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TRANSPORT_MODES = ("walking", "car", "bicycle", "public_transport", "motorcycle")
PREFERENCE_STRENGTHS = ("very_high", "high", "medium", "low")
WALKING_DISTANCE_LIMIT_METERS = 5000


def discovery_radius_meters(profile: "MobilityProfile | None") -> int:
    """Choose a factual search extent from declared local mobility.

    This is a discovery boundary, not a claim that every candidate is suitable;
    ORS and validation still decide route compatibility later.
    """
    if profile is None or profile.preferred_transport is None:
        return 10_000
    if profile.mixed_strategy and profile.allows("car"):
        return 30_000
    if profile.walking_only or profile.preferred_transport == "walking":
        return 5_000
    if profile.preferred_transport == "bicycle":
        return 12_000
    if profile.preferred_transport in {"car", "motorcycle"} or profile.mixed_strategy:
        return 30_000
    return 15_000


@dataclass(frozen=True)
class MobilityProfile:
    preferred_transport: str | None = None
    allowed_transport_modes: tuple[str, ...] | None = None
    driving_license: bool | None = None
    own_car: bool | None = None
    rental_car_allowed: bool | None = None
    rental_bicycle_allowed: bool | None = None
    walking_preference: str | None = None
    public_transport_preference: str | None = None
    bicycle_preference: str | None = None
    motorcycle_preference: str | None = None
    car_usage: bool | None = None
    public_transport_usage: bool | None = None
    mixed_strategy: bool | None = None
    city_transport: str | None = None
    outside_city_transport: str | None = None

    @classmethod
    def unknown(cls) -> "MobilityProfile":
        return cls()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MobilityProfile":
        def mode(field: str) -> str | None:
            item = value.get(field)
            return item if item in TRANSPORT_MODES else None

        raw_modes = value.get("allowed_transport_modes")
        modes = tuple(item for item in raw_modes if item in TRANSPORT_MODES) if isinstance(raw_modes, list) else None
        def boolean(field: str) -> bool | None:
            item = value.get(field)
            return item if isinstance(item, bool) else None
        def strength(field: str) -> str | None:
            item = value.get(field)
            return item if item in PREFERENCE_STRENGTHS else None
        return cls(
            preferred_transport=mode("preferred_transport"), allowed_transport_modes=modes,
            driving_license=boolean("driving_license"), own_car=boolean("own_car"),
            rental_car_allowed=boolean("rental_car_allowed"), rental_bicycle_allowed=boolean("rental_bicycle_allowed"),
            walking_preference=strength("walking_preference"), public_transport_preference=strength("public_transport_preference"),
            bicycle_preference=strength("bicycle_preference"), motorcycle_preference=strength("motorcycle_preference"),
            car_usage=boolean("car_usage"), public_transport_usage=boolean("public_transport_usage"),
            mixed_strategy=boolean("mixed_strategy"), city_transport=mode("city_transport"),
            outside_city_transport=mode("outside_city_transport"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preferred_transport": self.preferred_transport,
            "allowed_transport_modes": list(self.allowed_transport_modes) if self.allowed_transport_modes is not None else None,
            "driving_license": self.driving_license, "own_car": self.own_car,
            "rental_car_allowed": self.rental_car_allowed, "rental_bicycle_allowed": self.rental_bicycle_allowed,
            "walking_preference": self.walking_preference,
            "public_transport_preference": self.public_transport_preference,
            "bicycle_preference": self.bicycle_preference, "motorcycle_preference": self.motorcycle_preference,
            "car_usage": self.car_usage, "public_transport_usage": self.public_transport_usage,
            "mixed_strategy": self.mixed_strategy, "city_transport": self.city_transport,
            "outside_city_transport": self.outside_city_transport,
        }

    @property
    def walking_only(self) -> bool:
        return self.allowed_transport_modes == ("walking",) or (
            self.walking_preference == "very_high" and self.car_usage is False and self.public_transport_usage is False
        )

    def planning_mode(self) -> str | None:
        return self.city_transport or self.preferred_transport

    def allows(self, mode: str) -> bool | None:
        if self.allowed_transport_modes is None:
            return None
        return mode in self.allowed_transport_modes

    def mobility_score(self, descriptors: set[str], distance_meters: float | None) -> float:
        """Score only verified category/geometry evidence; no route time is inferred."""
        score = 0.0
        if self.walking_only and distance_meters is not None:
            score += 3 if distance_meters <= 1500 else 1 if distance_meters <= 3000 else -12 if distance_meters > WALKING_DISTANCE_LIMIT_METERS else 0
        elif self.walking_preference in {"high", "very_high"} and distance_meters is not None:
            score += 2 if distance_meters <= 1500 else -3 if distance_meters > WALKING_DISTANCE_LIMIT_METERS else 0
        if self.bicycle_preference in {"high", "very_high"} and ("bicycle" in descriptors or "cycleway" in descriptors):
            score += 2
        if self.rental_car_allowed is True and self.preferred_transport == "car" and {"rental", "car"}.issubset(descriptors):
            score += 2
        if self.rental_car_allowed is False and {"rental", "car"}.issubset(descriptors):
            score -= 8
        return score
