"""Offline tests for verified quality evidence and explainable deterministic ranking."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.ai.intent_analyzer import IntentPreference
from app.travel.place import Place
from app.travel.place_quality import score_quality
from app.travel.place_ranking import rank_places


def place(name: str, categories: list[str], quality: dict | None = None) -> dict:
    return Place(
        name=name, address=f"{name} address", latitude=58.38, longitude=24.50,
        place_id=name.casefold().replace(" ", "-"), categories=categories,
        datasource={"sourcename": "openstreetmap"}, quality=quality,
    ).to_dict()


SOURCE = "verified test provider"


class PlaceQualityRankingTests(unittest.TestCase):
    def test_better_verified_rating_wins_when_places_are_equally_relevant(self) -> None:
        places = [
            place("Good Spa", ["leisure.spa"], {"rating": 4.8, "source": SOURCE}),
            place("Okay Spa", ["leisure.spa"], {"rating": 4.2, "source": SOURCE}),
        ]
        ranked = rank_places(places, [IntentPreference("spa", "high", "positive")])
        self.assertEqual(ranked[0].place["name"], "Good Spa")
        self.assertEqual(ranked[0].preference_score, ranked[1].preference_score)
        self.assertGreater(ranked[0].quality_score, ranked[1].quality_score)

    def test_review_volume_breaks_a_same_rating_tie_without_becoming_quality(self) -> None:
        places = [
            place("More Evidence", ["leisure.spa"], {"rating": 4.5, "review_count": 500, "source": SOURCE}),
            place("Less Evidence", ["leisure.spa"], {"rating": 4.5, "review_count": 10, "source": SOURCE}),
        ]
        ranked = rank_places(places, [IntentPreference("spa", "high", "positive")])
        self.assertEqual(ranked[0].place["name"], "More Evidence")
        self.assertEqual(ranked[0].quality_score, ranked[1].quality_score)
        self.assertGreater(ranked[0].popularity_score, ranked[1].popularity_score)

    def test_strong_negative_preference_beats_high_quality_and_popularity(self) -> None:
        places = [
            place("Popular Museum", ["entertainment.museum"], {
                "rating": 5.0, "review_count": 1_000_000, "popularity": 1.0, "source": SOURCE,
            }),
            place("Quiet Park", ["leisure.park"]),
        ]
        ranked = rank_places(places, [IntentPreference("museum", "very_high", "negative")])
        self.assertEqual(ranked[0].place["name"], "Quiet Park")
        self.assertTrue(ranked[-1].has_strong_negative_conflict)

    def test_absent_quality_data_stays_absent(self) -> None:
        candidate = place("Plain Park", ["leisure.park"])
        score = score_quality(candidate)
        self.assertEqual(score.quality_score, 0)
        self.assertEqual(score.popularity_score, 0)
        self.assertIsNone(score.signals.rating)
        self.assertIsNone(score.signals.review_count)
        self.assertIn("No verified rating", score.explanation())
        self.assertNotIn("rating", candidate)

    def test_only_rating_is_supported_without_inventing_reviews(self) -> None:
        score = score_quality(place("Rated Spa", ["leisure.spa"], {"rating": 4.6, "source": SOURCE}))
        self.assertEqual(score.quality_score, 4.6)
        self.assertEqual(score.popularity_score, 0)
        self.assertIsNone(score.signals.review_count)

    def test_only_review_count_is_supported_without_inventing_rating(self) -> None:
        score = score_quality(place("Reviewed Spa", ["leisure.spa"], {"review_count": 100, "source": SOURCE}))
        self.assertEqual(score.quality_score, 0)
        self.assertGreater(score.popularity_score, 0)
        self.assertIsNone(score.signals.rating)

    def test_preference_and_quality_scores_remain_separate(self) -> None:
        ranked = rank_places(
            [place("Rated Spa", ["leisure.spa"], {"rating": 4.7, "source": SOURCE})],
            [IntentPreference("spa", "high", "positive")],
        )[0]
        self.assertEqual(ranked.preference_score, 5)
        self.assertEqual(ranked.quality_score, 4.7)
        self.assertEqual(
            ranked.final_score,
            round(ranked.preference_score + ranked.relevance_score + ranked.quality_score + ranked.popularity_score + ranked.data_confidence_score, 2),
        )

    def test_accommodations_use_the_same_quality_architecture(self) -> None:
        hotels = [
            place("Higher Rated Hotel", ["accommodation.hotel"], {"rating": 4.6, "source": SOURCE}),
            place("Lower Rated Hotel", ["accommodation.hotel"], {"rating": 4.0, "source": SOURCE}),
        ]
        ranked = rank_places(hotels, [])
        self.assertEqual(ranked[0].place["name"], "Higher Rated Hotel")

    def test_ranking_is_deterministic(self) -> None:
        places = [
            place("Beta", ["leisure.park"]),
            place("Alpha", ["leisure.park"]),
        ]
        first = [item.place["name"] for item in rank_places(places, [])]
        second = [item.place["name"] for item in rank_places(places, [])]
        self.assertEqual(first, second)
        self.assertEqual(first, ["Alpha", "Beta"])

    def test_explanation_does_not_claim_unavailable_evidence(self) -> None:
        ranked = rank_places([place("Plain Spa", ["leisure.spa"])], [IntentPreference("spa", "high", "positive")])[0]
        self.assertIn("No verified rating", ranked.quality_explanation)
        self.assertNotIn("4.", ranked.quality_explanation)


if __name__ == "__main__":
    unittest.main()
