"""
Similarity detection for duplicate-product prevention (requirement #13:
title, feature, keyword, and design similarity checked separately).

Deliberately implemented with pure-Python token/Jaccard similarity rather
than an embeddings model or scikit-learn: at MVP scale (a handful of
products per run, dozens over time) this is accurate enough, has zero
extra dependency weight, and needs no GPU/heavy CPU work on a GitHub
Actions runner. If this ever becomes insufficient, swap the scoring
functions below for an embedding-based ResearchProvider-style adapter —
callers only depend on `similarity_score` and `SimilarityReport`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.core.models import ProductRecord, ProductSpec

# Below this Jaccard score, two token sets are considered unrelated.
_STOPWORDS = {
    "a", "an", "the", "for", "and", "or", "of", "to", "with", "your",
    "tracker", "template", "budget", "finance", "planner",  # generic, near-universal in this category
}


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return round(len(a & b) / len(union), 4)


def title_fingerprint(title: str) -> str:
    return " ".join(sorted(_tokenize(title)))


def feature_fingerprint(features: list[str]) -> str:
    tokens: set[str] = set()
    for f in features:
        tokens |= _tokenize(f)
    return " ".join(sorted(tokens))


def keyword_fingerprint(keywords: list[str]) -> str:
    tokens = {k.strip().lower() for k in keywords if k.strip()}
    return " ".join(sorted(tokens))


def design_fingerprint(design_profile_id: str, niche: str) -> str:
    # Design similarity is meaningful only within the same niche — the
    # same design profile used across two different niches is not a
    # duplicate, it's expected reuse of a style.
    return f"{niche}:{design_profile_id}"


@dataclass
class SimilarityScore:
    title: float
    features: float
    keywords: float
    design_exact_match: bool


@dataclass
class SimilarityReport:
    is_too_similar: bool
    best_match_product_id: str | None
    best_match_score: SimilarityScore | None
    threshold_used: float


class SimilarityChecker:
    """Compares a candidate ProductSpec against previously stored
    products and decides whether it is too similar to ship as-is."""

    def __init__(
        self,
        title_threshold: float = 0.6,
        feature_threshold: float = 0.7,
        keyword_threshold: float = 0.7,
        # A candidate is rejected if title AND features are both over
        # threshold (near-duplicate content), OR if all three dimensions
        # individually exceed a slightly lower combined bar.
        combined_threshold: float = 0.55,
    ):
        self.title_threshold = title_threshold
        self.feature_threshold = feature_threshold
        self.keyword_threshold = keyword_threshold
        self.combined_threshold = combined_threshold

    def score_against(
        self,
        candidate: ProductSpec,
        existing: ProductRecord,
        candidate_design_profile: str | None = None,
    ) -> SimilarityScore:
        title_sim = _jaccard(_tokenize(candidate.title), _tokenize(existing.title))
        features_sim = _jaccard(
            _tokenize(" ".join(candidate.core_features + candidate.optional_features)),
            _tokenize(" ".join(existing.features)),
        )
        keywords_sim = _jaccard(
            {k.lower() for k in candidate.keywords},
            {k.lower() for k in existing.keywords},
        )
        # Design similarity is only meaningful once a design profile has
        # actually been assigned to the candidate (this happens after the
        # design step, later than title/feature/keyword checks which can
        # run right after strategy). When no candidate profile is given
        # yet, we simply don't claim a design match rather than guessing.
        design_exact = (
            candidate_design_profile is not None
            and existing.niche == candidate.niche
            and existing.design_profile == candidate_design_profile
        )
        return SimilarityScore(
            title=title_sim, features=features_sim, keywords=keywords_sim,
            design_exact_match=design_exact,
        )

    def check(
        self,
        candidate: ProductSpec,
        history: list[ProductRecord],
        candidate_design_profile: str | None = None,
    ) -> SimilarityReport:
        same_niche_history = [p for p in history if p.niche == candidate.niche]
        if not same_niche_history:
            return SimilarityReport(
                is_too_similar=False, best_match_product_id=None,
                best_match_score=None, threshold_used=self.combined_threshold,
            )

        worst_offender: tuple[str, SimilarityScore, float] | None = None
        for existing in same_niche_history:
            score = self.score_against(candidate, existing, candidate_design_profile)
            combined = (score.title + score.features + score.keywords) / 3
            # A design-exact-match on top of moderate content overlap is
            # treated as reinforcing evidence of duplication, not scored
            # into `combined` directly (design alone shouldn't fail a
            # product that solves a different problem for a different
            # target customer).
            if score.design_exact_match:
                combined = max(combined, combined + 0.1)
            if worst_offender is None or combined > worst_offender[2]:
                worst_offender = (existing.product_id, score, combined)

        assert worst_offender is not None
        best_match_id, best_score, combined = worst_offender

        is_duplicate = (
            (best_score.title >= self.title_threshold and best_score.features >= self.feature_threshold)
            or combined >= self.combined_threshold
        )

        return SimilarityReport(
            is_too_similar=is_duplicate,
            best_match_product_id=best_match_id if is_duplicate else None,
            best_match_score=best_score,
            threshold_used=self.combined_threshold,
        )
