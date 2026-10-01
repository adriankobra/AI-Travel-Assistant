"""A small, consistent representation of a place returned by Geoapify."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable


@dataclass(frozen=True)
class Place:
    """Normalized Geoapify place data shared by accommodation and activity searches."""

    name: str
    address: str
    latitude: float | None
    longitude: float | None
    place_id: str | None
    categories: list[str]
    place_type: str | None = None
    city: str | None = None
    country: str | None = None
    datasource: dict[str, Any] | None = None
    distance_meters: float | None = None
    # Geoapify does not currently populate this. It is reserved for a future,
    # explicitly named external quality provider and omitted when unavailable.
    quality: dict[str, Any] | None = None

    @classmethod
    def from_geoapify(cls, properties: dict[str, Any], *, place_type: str | None = None) -> "Place | None":
        """Create a place when Geoapify provides the only required field: a name."""
        name = properties.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        categories = properties.get("categories", [])
        if not isinstance(categories, list):
            categories = []
        return cls(
            name=name.strip(),
            address=properties.get("formatted") or "Address unavailable",
            latitude=properties.get("lat"),
            longitude=properties.get("lon"),
            place_id=properties.get("place_id"),
            categories=[str(category) for category in categories],
            place_type=place_type,
            city=properties.get("city") if isinstance(properties.get("city"), str) else None,
            country=properties.get("country") if isinstance(properties.get("country"), str) else None,
            datasource={
                key: value for key, value in properties["datasource"].items()
                if key in {"sourcename", "attribution", "license", "url"}
            } if isinstance(properties.get("datasource"), dict) else None,
            distance_meters=float(properties["distance"]) if isinstance(properties.get("distance"), (int, float)) and properties["distance"] >= 0 else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Keep the existing dictionary contract used by the recommender and UI."""
        result: dict[str, Any] = {
            "name": self.name, "address": self.address,
            "latitude": self.latitude, "longitude": self.longitude,
            "place_id": self.place_id, "categories": self.categories,
        }
        if self.place_type:
            result["type"] = self.place_type
        if self.city:
            result["city"] = self.city
        if self.country:
            result["country"] = self.country
        if self.datasource:
            result["datasource"] = self.datasource
        if self.distance_meters is not None:
            result["distance_meters"] = self.distance_meters
        if self.quality:
            result["quality"] = self.quality
        return result


def deduplicate_places(places: Iterable[Place]) -> list[Place]:
    """Deduplicate one factual Geoapify place while retaining all returned categories."""
    unique: dict[str, Place] = {}
    identities_by_name: dict[str, str] = {}
    for place in places:
        normalized_name = " ".join(place.name.casefold().split())
        fallback = f"name:{normalized_name}:{place.latitude}:{place.longitude}"
        identity = f"id:{place.place_id}" if place.place_id else fallback
        # Geoapify can return a POI and its building representation separately.
        # A repeated named place is one itinerary candidate, even when IDs differ.
        identity = identities_by_name.setdefault(normalized_name, identity)
        previous = unique.get(identity)
        if previous is None:
            unique[identity] = place
            continue
        categories = list(dict.fromkeys([*previous.categories, *place.categories]))
        unique[identity] = replace(previous, categories=categories)
    return list(unique.values())
