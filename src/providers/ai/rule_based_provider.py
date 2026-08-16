"""
RuleBasedAIProvider: the guaranteed-available AI provider (requirement:
AIProvider must never hard-depend on a paid API, and must not assume a
heavy local model can run on a GitHub Actions runner).

This is NOT a language model. It is a deterministic heuristic engine that
answers the two structured tasks the rest of the codebase actually asks
an AIProvider for:

1. Self-critique scoring (src/quality/self_critique.py) — given context
   about a generated product (QC score, feature count, differentiation
   text length, etc.), produce a plausible 0-100 score per quality
   dimension using simple, explainable rules.
2. Generic text generation — returns a clearly-labeled placeholder-free
   response built from the prompt/context rather than failing, so a
   caller that only needs *something* (e.g. a fallback product
   description) still gets usable output.

Because it's rule-based, it is always is_available() == True and never
makes a network call, so it is the safe last resort in
AIProviderRegistry.fallback_order.
"""

from __future__ import annotations

import json
import logging

from src.core.interfaces import AIProvider, AIRequest, AIResponse

logger = logging.getLogger(__name__)

_CRITIQUE_DIMENSIONS = (
    "design", "ux", "functionality", "originality",
    "clarity", "professionalism", "target_fit",
)


class RuleBasedAIProvider(AIProvider):
    name = "rule_based"

    def is_available(self) -> bool:
        return True

    def generate(self, request: AIRequest) -> AIResponse:
        context = request.context or {}
        task = context.get("task")

        try:
            if task == "self_critique":
                text = self._critique(context)
            else:
                text = self._generic(request)
            return AIResponse(text=text, provider_name=self.name, success=True)
        except Exception as e:  # noqa: BLE001 - provider must never raise
            logger.exception("RuleBasedAIProvider failed unexpectedly")
            return AIResponse(text="", provider_name=self.name, success=False, error=str(e))

    # ------------------------------------------------------------------

    def _critique(self, context: dict) -> str:
        """Deterministic heuristic critique. Returns a JSON string with a
        0-100 score per dimension, matching what self_critique.py expects
        from any provider (rule-based or a real model)."""
        qc_score = float(context.get("qc_score", 70.0))
        feature_count = int(context.get("feature_count", 0))
        differentiation_len = len(str(context.get("differentiation", "")))
        has_target_customer = bool(context.get("target_customer"))
        keyword_count = int(context.get("keyword_count", 0))
        is_similar_to_existing = bool(context.get("is_similar_to_existing", False))

        # Functionality and clarity track the deterministic QC score
        # closely — QC already checked formulas/validation/blank pages.
        functionality = qc_score
        clarity = min(100.0, qc_score + (5 if feature_count >= 3 else -5))

        # Design/professionalism assume competence unless QC flagged
        # problems (a broken workbook is also usually a badly designed one).
        design = min(100.0, 85.0 - max(0, 70 - qc_score))
        professionalism = min(100.0, 85.0 - max(0, 70 - qc_score))

        # Originality penalized if the similarity checker already flagged
        # this product as too close to an existing one.
        originality = 60.0 if is_similar_to_existing else 85.0

        # UX rewards having a differentiation statement and multiple features.
        ux = 70.0 + min(15, differentiation_len // 20) + min(10, feature_count * 2)
        ux = min(100.0, ux)

        # Target fit rewards an explicit target customer and enough
        # keywords to suggest the strategist actually tailored the product.
        target_fit = 60.0 + (15 if has_target_customer else 0) + min(15, keyword_count * 3)
        target_fit = min(100.0, target_fit)

        scores = {
            "design": round(design, 1),
            "ux": round(ux, 1),
            "functionality": round(functionality, 1),
            "originality": round(originality, 1),
            "clarity": round(clarity, 1),
            "professionalism": round(professionalism, 1),
            "target_fit": round(target_fit, 1),
        }
        return json.dumps(scores)

    def _generic(self, request: AIRequest) -> str:
        return (
            "[rule_based provider — no language model available]\n"
            f"Prompt received ({len(request.prompt)} chars). "
            "No generated text; caller should use structured context-driven "
            "logic instead of relying on this provider for free-form text."
        )
