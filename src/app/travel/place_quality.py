"""Verified quality evidence and deterministic score components for places.

Geoapify Places does not currently supply ratings, review counts, or popularity
in this integration.  The optional ``quality`` mapping exists only as a safe
extension point for a future provider and is ignored unless it names a source.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log10
from typing import Any


@dataclass(frozen=True)
class QualitySignals:
    rating: float | None = None
    review_count: int | None = None
    popularity: float | None = None
    source: str | None = None

    @classmethod
    def from_place(cls, place: dict[str, Any]) -> "QualitySignals":
        raw = place.get("quality")
        if not isinstance(raw, dict) or not isinstance(raw.get("source"), str) or not raw["source"].strip():
            return cls()
        rating = raw.get("rating")
        reviews = raw.get("review_count")
        popularity = raw.get("popularity")
        return cls(
            rating=float(rating) if isinstance(rating, (int, float)) and 0 <= rating <= 5 else None,
            review_count=int(reviews) if isinstance(reviews, int) and reviews >= 0 else None,
            popularity=float(popularity) if isinstance(popularity, (int, float)) and 0 <= popularity <= 1 else None,
            source=raw["source"].strip(),
        )


@dataclass(frozen=True)
class QualityScore:
    quality_score: float
    popularity_score: float
    data_confidence_score: float
    signals: QualitySignals

    def explanation(self) -> str:
        """Describe only fields supplied by a named external source."""
        details: list[str] = []
        if self.signals.rating is not None:
            details.append(f"verified external rating {self.signals.rating:g}/5")
        if self.signals.review_count is not None:
            details.append(f"verified review count {self.signals.review_count}")
        if self.signals.popularity is not None:
            details.append("a verified external popularity signal")
        if not details:
            return "No verified rating, review-count, or popularity data is available."
        return f"Quality evidence from {self.signals.source}: " + "; ".join(details) + "."


def score_quality(place: dict[str, Any]) -> QualityScore:
    """Calculate bounded deterministic components; never infer absent evidence."""
    signals = QualitySignals.from_place(place)
    # Rating is a quality signal only. Review volume and popularity remain separate.
    quality_score = signals.rating or 0.0
    review_evidence = min(log10(signals.review_count + 1), 3.0) if signals.review_count is not None else 0.0
    popularity_evidence = (signals.popularity * 3.0) if signals.popularity is not None else 0.0
    # Completeness is not quality: it only makes a tied ranking more transparent.
    completeness = sum((
        isinstance(place.get("name"), str) and bool(place["name"].strip()),
        isinstance(place.get("address"), str) and bool(place["address"].strip()),
        isinstance(place.get("categories"), list) and bool(place["categories"]),
        place.get("place_id") is not None,
        place.get("latitude") is not None and place.get("longitude") is not None,
        isinstance(place.get("datasource"), dict) and bool(place["datasource"]),
    ))
    return QualityScore(
        quality_score=quality_score,
        popularity_score=review_evidence + popularity_evidence,
        data_confidence_score=round(completeness / 6, 2),
        signals=signals,
    )
