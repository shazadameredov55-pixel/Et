"""
OpportunityScorer: converts aggregated ResearchResult signals into an
OpportunityScore using the weights in config/scoring.yaml. Requirement
(Phase 3 #2): decide based on demand+competition+differentiation+
production ease together, not demand alone; weights configurable without
code changes.
"""

from __future__ import annotations

import logging

import yaml

from src.core.interfaces import ResearchResult
from src.core.models import OpportunityScore
from src.generators.blueprints import ProductBlueprint

logger = logging.getLogger(__name__)

_REQUIRED_WEIGHT_KEYS = (
    "demand", "competition", "differentiation",
    "commercial_potential", "usability", "production_ease",
)


class InvalidScoringConfigError(Exception):
    pass


class OpportunityScorer:
    def __init__(self, scoring_config_path: str = "config/scoring.yaml"):
        with open(scoring_config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        self.weights: dict[str, float] = config["weights"]
        self._validate_weights()
        self.minimum_score_to_notify: float = config.get("minimum_score_to_notify", 6.5)

    def _validate_weights(self) -> None:
        missing = set(_REQUIRED_WEIGHT_KEYS) - set(self.weights.keys())
        if missing:
            raise InvalidScoringConfigError(f"scoring.yaml is missing weight keys: {missing}")
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise InvalidScoringConfigError(f"scoring.yaml weights must sum to 1.0, got {total}")

    def score(
        self,
        niche: str,
        research_results: list[ResearchResult],
        blueprint: ProductBlueprint,
    ) -> OpportunityScore:
        """Derives 0-10 sub-scores from available research signals. When
        signals are sparse (e.g. no research sources configured — see
        NullResearchProvider), falls back to conservative, clearly-labeled
        midpoint estimates rather than fabricating confident numbers."""
        demand = self._demand_from_signals(research_results)
        competition = self._competition_from_signals(research_results)
        # Differentiation and production ease are properties of what we
        # WOULD build (the blueprint), not something scraped from the web
        # — a niche with more distinct sheets/formulas than usual is
        # judged more differentiated but also somewhat harder to produce.
        differentiation = min(10.0, 5.0 + len(blueprint.sheets) * 0.5)
        production_ease = max(1.0, 10.0 - len(blueprint.sheets) * 0.7)
        commercial_potential = round((demand + (10 - competition)) / 2, 2)
        usability = 7.5  # blueprints always include an Instructions sheet; stable baseline

        weighted_total = round(
            demand * self.weights["demand"]
            + competition * self.weights["competition"]
            + differentiation * self.weights["differentiation"]
            + commercial_potential * self.weights["commercial_potential"]
            + usability * self.weights["usability"]
            + production_ease * self.weights["production_ease"],
            2,
        )

        reasoning = self._build_reasoning(research_results, demand, competition)

        return OpportunityScore(
            demand=demand, competition=competition, differentiation=differentiation,
            commercial_potential=commercial_potential, usability=usability,
            production_ease=production_ease, weighted_total=weighted_total,
            reasoning=reasoning,
        )

    # ------------------------------------------------------------------

    def _demand_from_signals(self, results: list[ResearchResult]) -> float:
        ratios: list[float] = []
        for result in results:
            if not result.success:
                continue
            for signal in result.signals:
                if signal.signal_type == "demand_proxy":
                    ratios.append(signal.payload.get("match_ratio", 0.0))
        if not ratios:
            return 5.0  # no data: neutral midpoint, not a fabricated high score
        avg_ratio = sum(ratios) / len(ratios)
        return round(min(10.0, avg_ratio * 20), 2)  # a 50% match ratio -> 10.0

    def _competition_from_signals(self, results: list[ResearchResult]) -> float:
        """Returns competition already inverted: HIGHER = LESS competition
        = better, matching OpportunityScore's documented convention."""
        mention_counts: list[int] = []
        for result in results:
            if not result.success:
                continue
            for signal in result.signals:
                if signal.signal_type == "competition_proxy":
                    mention_counts.append(signal.payload.get("total_keyword_mentions", 0))
        if not mention_counts:
            return 5.0
        avg_mentions = sum(mention_counts) / len(mention_counts)
        # More mentions found -> more existing competition -> lower (inverted) score.
        return round(max(0.0, 10.0 - min(10.0, avg_mentions / 3)), 2)

    def _build_reasoning(self, results: list[ResearchResult], demand: float, competition: float) -> str:
        sources_used = [r.provider_name for r in results if r.success and r.signals]
        if not sources_used:
            return "No research signals available; scored using neutral baseline estimates."
        return (
            f"Based on signals from {', '.join(sources_used)}: "
            f"demand proxy {demand}/10, competition (inverted) {competition}/10."
        )
