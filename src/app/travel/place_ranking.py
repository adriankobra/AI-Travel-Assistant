"""Transparent ranking of verified Geoapify places against interpreted user intent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.ai.intent_analyzer import IntentPreference
from app.travel.category_config import CATEGORY_IMPORTANCE_WEIGHTS, CONCEPT_CATEGORY_TERMS
from app.travel.place_quality import QualityScore, score_quality
from app.travel.mobility import MobilityProfile


STRENGTH_WEIGHTS = {"very_high": 8, "high": 5, "medium": 3, "low": 1}

# This is a matching vocabulary, not a closed preference taxonomy. New LLM concepts
# remain valid and simply receive no factual match until an available data source supports them.

@dataclass(frozen=True)
class RankedPlace:
    place: dict[str, Any]
    # ``score`` is retained for callers from Phase 4.1; it equals final_score.
    score: float
    preference_score: int
    relevance_score: int
    quality_score: float
    popularity_score: float
    data_confidence_score: float
    final_score: float
    matched_concepts: tuple[str, ...]
    has_strong_negative_conflict: bool
    quality_explanation: str
    mobility_score: float = 0.0


def rank_places(places: Iterable[dict[str, Any]], intents: Iterable[IntentPreference], mobility_profile: MobilityProfile | None = None) -> list[RankedPlace]:
    """Rank only with verified category metadata; never infer facilities from a name."""
    intent_list = list(intents)
    ranked = [_score_place(place, intent_list, mobility_profile) for place in places if isinstance(place, dict)]
    # A strong explicit dislike is a hard ordering guard: quality/popularity can
    # break ties among relevant places but cannot elevate a conflicting category.
    return sorted(
        ranked,
        key=lambda item: (item.has_strong_negative_conflict, -item.final_score, item.place.get("name", "").casefold()),
    )


def unmatched_positive_concepts(intents: Iterable[IntentPreference], ranked_places: Iterable[RankedPlace]) -> list[str]:
    """Return requested concepts for which the supplied verified data had no match."""
    matched = {concept for item in ranked_places for concept in item.matched_concepts}
    return [intent.concept for intent in intents if intent.polarity == "positive" and intent.concept not in matched]


def _score_place(place: dict[str, Any], intents: list[IntentPreference], mobility_profile: MobilityProfile | None = None) -> RankedPlace:
    descriptors = _category_descriptors(place.get("categories", []))
    relevance_score = sum(weight for category, weight in CATEGORY_IMPORTANCE_WEIGHTS.items() if category in descriptors)
    preference_score = 0
    matches: list[str] = []
    strong_negative_conflict = False
    for intent in intents:
        terms = _terms_for(intent.concept)
        if terms.intersection(descriptors):
            matches.append(intent.concept)
            weight = STRENGTH_WEIGHTS[intent.strength]
            if intent.polarity == "positive":
                preference_score += weight
            else:
                preference_score -= weight * 2
                strong_negative_conflict = strong_negative_conflict or intent.strength in {"high", "very_high"}
    quality: QualityScore = score_quality(place)
    mobility_score = mobility_profile.mobility_score(descriptors, _distance_meters(place)) if mobility_profile else 0.0
    final_score = round(
        preference_score + relevance_score + quality.quality_score + quality.popularity_score + quality.data_confidence_score + mobility_score,
        2,
    )
    return RankedPlace(
        place=place,
        score=final_score,
        preference_score=preference_score,
        relevance_score=relevance_score,
        quality_score=quality.quality_score,
        popularity_score=quality.popularity_score,
        data_confidence_score=quality.data_confidence_score,
        final_score=final_score,
        matched_concepts=tuple(matches),
        has_strong_negative_conflict=strong_negative_conflict,
        quality_explanation=quality.explanation(),
        mobility_score=mobility_score,
    )


def _category_descriptors(categories: object) -> set[str]:
    if not isinstance(categories, list):
        return set()
    descriptors: set[str] = set()
    for category in categories:
        value = str(category).casefold().replace("-", "_").replace(" ", "_")
        descriptors.add(value)
        descriptors.update(value.split("."))
    return descriptors


def _terms_for(concept: str) -> set[str]:
    normalized = concept.casefold().replace("-", "_").replace(" ", "_")
    return {normalized, *CONCEPT_CATEGORY_TERMS.get(normalized, set())}


def _distance_meters(place: dict[str, Any]) -> float | None:
    value = place.get("distance_meters")
    return float(value) if isinstance(value, (int, float)) and value >= 0 else None
