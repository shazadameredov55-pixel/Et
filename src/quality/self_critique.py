"""
AI self-critique (Phase 2/3 requirement #9): scores Design, UX,
Functionality, Originality, Clarity, Professionalism, and Target
Customer Fit each 0-100, combines with the deterministic QCResult, and
decides whether the product needs a revision.

The "AI" here is whatever AIProviderRegistry resolves to — a real
language model if AI_API_URL is configured, or RuleBasedAIProvider's
deterministic heuristic otherwise. Either way, the CONTRACT is the same:
a JSON object with 7 numeric scores. If the provider's response can't be
parsed as that JSON, this module never fabricates a passing score — it
falls back to a purely-QC-based score, which is always the safe (i.e.
harder to pass) choice.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from src.core.interfaces import AIRequest
from src.core.models import ProductSpec, QCResult
from src.providers.ai.registry import AIProviderRegistry

logger = logging.getLogger(__name__)

_DIMENSIONS = (
    "design", "ux", "functionality", "originality",
    "clarity", "professionalism", "target_fit",
)


@dataclass
class CritiqueResult:
    dimension_scores: dict[str, float]
    overall_score: float
    needs_revision: bool
    provider_name: str
    notes: str = ""


class SelfCritiqueEngine:
    def __init__(self, registry: AIProviderRegistry | None = None, minimum_pass_score: float = 80.0):
        self.registry = registry or AIProviderRegistry.default()
        self.minimum_pass_score = minimum_pass_score

    def critique(
        self,
        product_spec: ProductSpec,
        qc_result: QCResult,
        is_similar_to_existing: bool = False,
    ) -> CritiqueResult:
        context = {
            "task": "self_critique",
            "qc_score": qc_result.score,
            "feature_count": len(product_spec.core_features),
            "differentiation": product_spec.differentiation,
            "target_customer": product_spec.target_customer,
            "keyword_count": len(product_spec.keywords),
            "is_similar_to_existing": is_similar_to_existing,
        }
        request = AIRequest(
            prompt=self._build_prompt(product_spec, qc_result),
            system_prompt=(
                "You are a strict but fair quality reviewer for personal-finance "
                "digital products. Respond with ONLY a JSON object with these "
                "exact keys, each a number 0-100: "
                "design, ux, functionality, originality, clarity, professionalism, target_fit."
            ),
            max_tokens=300,
            temperature=0.3,
            context=context,
        )

        response = self.registry.generate(request)
        scores = self._parse_scores(response.text) if response.success else None

        if scores is None:
            logger.warning(
                "Self-critique response could not be parsed (provider=%s); "
                "falling back to QC-score-only critique.",
                response.provider_name,
            )
            scores = {dim: qc_result.score for dim in _DIMENSIONS}
            provider_name = "qc_fallback"
        else:
            provider_name = response.provider_name

        overall = round(sum(scores.values()) / len(scores), 1)
        # A hard floor: QC already found real structural problems, no
        # qualitative critique should be able to paper over that.
        overall = min(overall, qc_result.score) if not qc_result.passed else overall
        needs_revision = overall < self.minimum_pass_score

        return CritiqueResult(
            dimension_scores=scores,
            overall_score=overall,
            needs_revision=needs_revision,
            provider_name=provider_name,
        )

    # ------------------------------------------------------------------

    def _build_prompt(self, spec: ProductSpec, qc_result: QCResult) -> str:
        issues_summary = "; ".join(f"{i.severity}:{i.code}" for i in qc_result.issues) or "none"
        return (
            f"Product title: {spec.title}\n"
            f"Target customer: {spec.target_customer}\n"
            f"Core features: {', '.join(spec.core_features)}\n"
            f"Differentiation: {spec.differentiation}\n"
            f"Automated QC score: {qc_result.score}/100\n"
            f"Automated QC issues: {issues_summary}\n"
            "Score this product's Design, UX, Functionality, Originality, "
            "Clarity, Professionalism, and Target Customer Fit, each 0-100."
        )

    def _parse_scores(self, text: str) -> dict[str, float] | None:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            # Some providers wrap JSON in prose/markdown fences; try to
            # extract the first {...} block before giving up.
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None

        if not isinstance(data, dict):
            return None

        scores: dict[str, float] = {}
        for dim in _DIMENSIONS:
            value = data.get(dim)
            if not isinstance(value, (int, float)):
                return None
            scores[dim] = max(0.0, min(100.0, float(value)))
        return scores
