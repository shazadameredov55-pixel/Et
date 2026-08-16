"""
ProductStrategist: turns an approved ProductIdea + niche blueprint into a
full ProductSpec (requirement Phase 1/3 #5: Target Customer, Problem,
Current Workaround, Desired Outcome, Core Features, Optional Features,
Differentiation, UX Approach before design/generation happens).

Uses AIProviderRegistry to draft the differentiation/problem narrative
text when a real provider is configured, but every STRUCTURAL field
(features, target customer, price) is grounded in the blueprint + a
deterministic pricing heuristic — never fabricated by an unreliable
text response, and never blocked if no AI provider produces usable text.
"""

from __future__ import annotations

import json
import logging

from src.core.interfaces import AIRequest
from src.core.models import ProductIdea, ProductSpec, new_id
from src.generators.blueprints import ProductBlueprint
from src.providers.ai.registry import AIProviderRegistry

logger = logging.getLogger(__name__)

# Target-customer archetypes per niche, used when the idea doesn't already
# specify one. Kept here (not invented per-call) so two products in the
# same niche without an explicit override get the same, sensible default
# — variation then comes from features/design, not from randomness.
_DEFAULT_PROBLEMS: dict[str, str] = {
    "monthly_budget_tracker": "Struggles to see where monthly income actually goes and overspends on non-essentials.",
    "freelancer_finance_tracker": "Irregular client income makes it hard to plan taxes and track what's actually profitable.",
    "debt_payoff_tracker": "Juggling multiple debts with no clear view of which to prioritize or how much progress is being made.",
}

_DEFAULT_WORKAROUNDS: dict[str, str] = {
    "monthly_budget_tracker": "A mix of banking app screenshots and a notes app list.",
    "freelancer_finance_tracker": "Scattered invoices and a shoebox of receipts checked once a quarter.",
    "debt_payoff_tracker": "Mental math and occasionally checking each lender's app separately.",
}

_DEFAULT_OUTCOMES: dict[str, str] = {
    "monthly_budget_tracker": "A clear, at-a-glance monthly picture of income vs. spending.",
    "freelancer_finance_tracker": "Confidence in quarterly tax set-asides and which clients are worth the time.",
    "debt_payoff_tracker": "A concrete, visible payoff plan with a progress percentage that updates automatically.",
}


class ProductStrategist:
    def __init__(self, registry: AIProviderRegistry | None = None):
        self.registry = registry or AIProviderRegistry.default()

    def build_spec(self, idea: ProductIdea, blueprint: ProductBlueprint) -> ProductSpec:
        target_customer = blueprint.default_target_customer
        problem = _DEFAULT_PROBLEMS.get(idea.niche, f"Needs a clearer way to manage {blueprint.display_name.lower()}.")
        workaround = _DEFAULT_WORKAROUNDS.get(idea.niche, "Manual spreadsheets or no system at all.")
        outcome = _DEFAULT_OUTCOMES.get(idea.niche, "A simple, reliable system that requires no manual math.")

        differentiation = self._draft_differentiation(idea, blueprint)
        price = self._suggest_price(blueprint)

        return ProductSpec(
            product_id=new_id(),
            run_id=idea.run_id,
            niche=idea.niche,
            title=idea.working_title or blueprint.display_name,
            target_customer=target_customer,
            problem=problem,
            current_workaround=workaround,
            desired_outcome=outcome,
            core_features=list(blueprint.default_features),
            optional_features=[],
            differentiation=differentiation,
            ux_approach=self._ux_approach_for(blueprint),
            visual_style_hint=blueprint.sheets[0].sheet_key if blueprint.sheets else "",
            file_formats=["xlsx", "pdf", "png"],
            keywords=self._derive_keywords(blueprint),
            price_suggestion=price,
        )

    # ------------------------------------------------------------------

    def _draft_differentiation(self, idea: ProductIdea, blueprint: ProductBlueprint) -> str:
        request = AIRequest(
            prompt=(
                f"In one sentence, describe what would make a '{blueprint.display_name}' "
                f"spreadsheet product genuinely useful and different from a generic template, "
                f"for someone whose core need is: {', '.join(blueprint.core_formulas)}."
            ),
            system_prompt="Answer with exactly one plain sentence, no preamble, no markdown.",
            max_tokens=100,
            temperature=0.6,
            context={"task": "differentiation_draft", "niche": idea.niche},
        )
        response = self.registry.generate(request)
        if response.success and response.text.strip() and "[rule_based provider" not in response.text:
            return response.text.strip().splitlines()[0][:300]

        # Deterministic fallback grounded in the blueprint itself — never
        # a placeholder string, always describes something real about
        # what this specific niche's workbook actually does.
        return (
            f"Structured specifically around {blueprint.core_formulas[0].lower()}, "
            f"not a generic budget grid relabeled for this niche."
        )

    def _ux_approach_for(self, blueprint: ProductBlueprint) -> str:
        sheet_count = len(blueprint.sheets)
        if sheet_count <= 3:
            return "single-glance simplicity: minimal navigation, everything visible fast"
        return "structured multi-tab workflow for users tracking several moving parts at once"

    def _suggest_price(self, blueprint: ProductBlueprint) -> float:
        # Deterministic heuristic: more sheets/complexity -> slightly
        # higher suggested price, within a sane digital-template range.
        base = 5.0
        return round(min(15.0, base + len(blueprint.sheets) * 1.25), 2)

    def _derive_keywords(self, blueprint: ProductBlueprint) -> list[str]:
        # Real per-niche Etsy tags (up to 13, each ≤20 chars) take
        # priority — these are actual buyer search phrases, not just the
        # product's own name split into words. Only fall back to the
        # generic word-split when a niche doesn't have curated tags yet.
        if blueprint.seo_keywords:
            return list(blueprint.seo_keywords[:13])

        words = blueprint.display_name.lower().split()
        keywords = [blueprint.display_name.lower(), "budget template", "excel spreadsheet"]
        keywords += [w for w in words if len(w) > 3]
        # De-duplicate while preserving order.
        seen = set()
        result = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                result.append(kw)
        return result[:10]
