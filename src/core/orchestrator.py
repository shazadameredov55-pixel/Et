"""
Orchestrator: the single place that wires together research, scoring,
memory, approval, strategy, design, generation, QC, self-critique,
revision, packaging, and Telegram delivery into the two GitHub Actions
entry points (`mode=research` and `mode=produce`).

Two modes exist because a GitHub Actions run is short-lived (requirement:
no persistent server) and Telegram approval happens asynchronously
between runs — see README.md for the full two-workflow architecture.

research mode:
    RESEARCHING -> (scoring, similarity check, pick best idea) -> WAITING_APPROVAL
    -> Telegram approval request sent -> run ends.

produce mode:
    Triggered by the Telegram bot's approve/reject action (via
    repository_dispatch -> workflow_dispatch with product_id + run_id).
    WAITING_APPROVAL -> STRATEGIZING -> GENERATING -> QUALITY_CHECK
    -> [REVISION -> GENERATING -> QUALITY_CHECK]* (max 3) -> PACKAGING
    -> READY -> Telegram delivery -> run ends.

Every stage is wrapped so an exception anywhere transitions the product
to FAILED (never a silent failure) and notifies Telegram.
"""

from __future__ import annotations

import logging
import os

import yaml

from src.core.models import ProductIdea, ProductRecord, ProductState, new_id
from src.core.state_machine import StaleApprovalError, IllegalTransitionError
from src.memory.db import get_connection, init_db
from src.memory.product_repository import ProductRepository, DuplicateRunError, ProductNotFoundError
from src.memory.similarity import SimilarityChecker
from src.generators.blueprints import get_blueprint, available_niches
from src.generators.xlsx_generator import XlsxGenerator
from src.generators.pdf_generator import PdfGenerator
from src.generators.preview_generator import PreviewGenerator
from src.generators.instructions_generator import InstructionsGenerator
from src.generators.listing_generator import build_listing_text
from src.generators.packager import Packager
from src.quality.qc_checks import QCEngine
from src.quality.self_critique import SelfCritiqueEngine
from src.scoring.opportunity_scorer import OpportunityScorer
from src.strategy.product_strategist import ProductStrategist
from src.design.profile_selector import ProfileSelector
from src.providers.research.registry import ResearchProviderRegistry
from src.providers.ai.registry import AIProviderRegistry
from src.providers.notification.telegram_provider import (
    TelegramNotificationProvider, format_opportunity_message, format_ready_message,
)

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        db_path: str = "data/products.db",
        output_dir: str = "output",
        settings_path: str = "config/settings.yaml",
    ):
        self.db_path = db_path
        self.output_dir = output_dir
        with open(settings_path, "r", encoding="utf-8") as f:
            self.settings = yaml.safe_load(f)

        self._conn = get_connection(db_path)
        init_db(self._conn)
        self.repo = ProductRepository(self._conn)

        self.scorer = OpportunityScorer()
        self.strategist = ProductStrategist()
        self.profile_selector = ProfileSelector()
        self.similarity_checker = SimilarityChecker()
        self.research_registry = ResearchProviderRegistry.default()
        self.ai_registry = AIProviderRegistry.default()
        self.qc_engine = QCEngine(minimum_pass_score=self.settings["quality"]["minimum_pass_score"])
        self.critique_engine = SelfCritiqueEngine(
            registry=self.ai_registry,
            minimum_pass_score=self.settings["quality"]["minimum_pass_score"],
        )
        self.max_revisions = self.settings["quality"]["max_revisions"]
        self.notifier = TelegramNotificationProvider()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # research mode
    # ------------------------------------------------------------------

    def run_research(self, run_id: str, category_niches: list[str] | None = None) -> ProductRecord | None:
        """Researches every candidate niche, scores each, rejects ideas
        too similar to prior products, and sends the single best
        surviving idea to Telegram for approval. Returns the created
        ProductRecord (state=WAITING_APPROVAL), or None if every
        candidate niche was rejected (nothing sent to Telegram, no error)."""
        self.repo.acquire_run_lock(run_id, mode="research")
        try:
            niches = category_niches or available_niches()
            candidates: list[tuple[ProductIdea, ProductRecord]] = []

            for niche in niches:
                blueprint = get_blueprint(niche)
                research_results = self.research_registry.research_all(niche, blueprint.display_name)
                for result in research_results:
                    for signal in result.signals:
                        self.repo.record_research_signal(
                            run_id, result.provider_name, niche, signal.signal_type,
                            _json_dumps(signal.payload),
                        )

                opp_score = self.scorer.score(niche, research_results, blueprint)
                if opp_score.weighted_total < self.scorer.minimum_score_to_notify:
                    logger.info("Niche %s scored below notify threshold (%.2f)", niche, opp_score.weighted_total)
                    continue

                idea = ProductIdea(
                    idea_id=new_id(), run_id=run_id, niche=niche,
                    working_title=blueprint.display_name,
                    opportunity_score=opp_score,
                )

                record = ProductRecord.new(run_id=run_id, niche=niche)
                record.title = idea.working_title
                record.opportunity_score = opp_score.weighted_total
                candidates.append((idea, record))

            if not candidates:
                logger.info("No niche cleared the notify threshold this run.")
                return None

            candidates.sort(key=lambda pair: pair[0].opportunity_score.weighted_total, reverse=True)

            # Try candidates in score order, falling through to the next
            # one if a candidate is rejected as too similar to an existing
            # product — NOT just giving up after the single best-scoring
            # idea. Without this, once one niche has a produced product,
            # it can keep winning "best idea" on ties/near-ties every
            # run (especially likely under the neutral baseline scores
            # used when no research sources are configured) and silently
            # block every other niche from ever being proposed.
            history = self.repo.recent(limit=200)
            from src.core.models import ProductSpec

            chosen_idea = None
            chosen_record = None
            for idea, record in candidates:
                provisional_spec = ProductSpec(
                    product_id="provisional", run_id=run_id, niche=idea.niche,
                    title=idea.working_title, target_customer="", problem="",
                    current_workaround="", desired_outcome="",
                    core_features=list(get_blueprint(idea.niche).default_features),
                    optional_features=[], differentiation="", ux_approach="",
                    visual_style_hint="",
                )
                similarity_report = self.similarity_checker.check(provisional_spec, history)
                if similarity_report.is_too_similar:
                    logger.info(
                        "Candidate idea for niche %s rejected as too similar to product %s; trying next candidate",
                        idea.niche, similarity_report.best_match_product_id,
                    )
                    continue
                chosen_idea, chosen_record = idea, record
                break

            if chosen_idea is None:
                logger.info("Every candidate this run was rejected as too similar to an existing product.")
                return None

            best_idea, best_record = chosen_idea, chosen_record

            self.repo.create(best_record)
            best_record = self.repo.transition(
                best_record.product_id, ProductState.WAITING_APPROVAL,
                actor="system", reason="research_complete",
            )

            message = format_opportunity_message(
                title=best_idea.working_title,
                target_customer=get_blueprint(best_idea.niche).default_target_customer,
                problem=f"See {best_idea.niche} blueprint for full problem statement.",
                opportunity_score=best_idea.opportunity_score.weighted_total,
                demand=best_idea.opportunity_score.demand,
                competition=best_idea.opportunity_score.competition,
                differentiation=best_idea.opportunity_score.differentiation,
                suggested_price=None,
                reasoning=best_idea.opportunity_score.reasoning,
                expected_files=["xlsx", "pdf", "png", "zip"],
            )
            result = self.notifier.send_approval_request(best_record.product_id, message, run_id=run_id)
            if not result.success:
                logger.warning("Failed to send Telegram approval request: %s", result.error)

            return best_record
        finally:
            self.repo.finish_run_lock(run_id)

    # ------------------------------------------------------------------
    # produce mode
    # ------------------------------------------------------------------

    def run_produce(self, product_id: str, expected_run_id: str, actor: str = "telegram") -> ProductRecord:
        """Drives WAITING_APPROVAL -> READY (or FAILED) for an approved
        product. Raises StaleApprovalError unchanged if the approval no
        longer matches state/run_id — the caller (Telegram bot handler)
        is responsible for reporting that back to the user; it is not
        swallowed here since silently no-op'ing would hide a real
        mismatch from the operator."""
        record = self.repo.approve(product_id, expected_run_id, actor=actor)

        try:
            record = self._strategize_and_generate(record)
            return record
        except Exception as e:  # noqa: BLE001 - top-level safety net
            logger.exception("Production pipeline failed for product %s", product_id)
            try:
                self.repo.fail(product_id, actor="system", reason=str(e))
            except IllegalTransitionError:
                pass  # already terminal
            self.notifier.send_message(
                f"<b>PRODUCT FAILED</b>\nProduct: {record.title}\nReason: {e}"
            )
            raise

    def _strategize_and_generate(self, record: ProductRecord) -> ProductRecord:
        blueprint = get_blueprint(record.niche)
        idea = ProductIdea(
            idea_id=new_id(), run_id=record.run_id, niche=record.niche,
            working_title=record.title,
            opportunity_score=self.scorer.score(record.niche, [], blueprint),
        )
        spec = self.strategist.build_spec(idea, blueprint)
        spec.product_id = record.product_id  # keep the same product_id throughout

        design_profile = self.profile_selector.select(spec)

        record.title = spec.title
        record.target_customer = spec.target_customer
        record.design_profile = design_profile.profile_id
        record.features = spec.core_features
        record.keywords = spec.keywords
        record.price_suggestion = spec.price_suggestion
        self.repo.save(record)

        record = self.repo.transition(record.product_id, ProductState.GENERATING, actor="system", reason="strategy_complete")

        revision_count = 0
        while True:
            gen_dir = os.path.join(self.output_dir, "_work", record.product_id)
            xlsx = XlsxGenerator().generate(spec, design_profile, gen_dir)
            pdf = PdfGenerator().generate(spec, design_profile, gen_dir)
            preview = PreviewGenerator().generate(spec, design_profile, gen_dir)
            instr = InstructionsGenerator().generate(spec, design_profile, gen_dir)

            for result, label in [(xlsx, "xlsx"), (pdf, "pdf"), (preview, "preview"), (instr, "instructions")]:
                if not result.success:
                    raise RuntimeError(f"{label} generation failed: {result.error}")

            listing_text = build_listing_text(spec, blueprint)
            source_files = {
                "xlsx": xlsx.files[0].file_path,
                "printable_pdf": pdf.files[0].file_path,
                "preview": preview.files[0].file_path,
                "instructions_pdf": instr.files[0].file_path,
            }
            package = Packager().package(
                spec, design_profile, blueprint, source_files, listing_text,
                quality_score=None, opportunity_score=idea.opportunity_score.weighted_total,
                base_output_dir=self.output_dir,
            )
            if not package.success:
                raise RuntimeError(f"Packaging failed: {package.error}")

            record = self.repo.transition(record.product_id, ProductState.QUALITY_CHECK, actor="system", reason="generation_complete")

            qc_result = self.qc_engine.check_package(spec, package.package_dir, package.zip_path)

            history = [r for r in self.repo.recent(limit=200) if r.product_id != record.product_id]
            similarity_report = self.similarity_checker.check(spec, history, candidate_design_profile=design_profile.profile_id)

            critique = self.critique_engine.critique(spec, qc_result, is_similar_to_existing=similarity_report.is_too_similar)

            record.quality_score = critique.overall_score
            self.repo.save(record)

            if not critique.needs_revision and qc_result.passed:
                record = self.repo.transition(record.product_id, ProductState.PACKAGING, actor="system", reason="qc_and_critique_passed")
                record = self.repo.transition(record.product_id, ProductState.READY, actor="system", reason="packaged")
                record.file_paths = [package.zip_path, package.package_dir]
                self.repo.save(record)

                self.repo.save_similarity_fingerprint(
                    record.product_id,
                    title_fingerprint=_lazy_title_fp(spec.title),
                    feature_fingerprint=_lazy_feature_fp(spec.core_features + spec.optional_features),
                    keyword_fingerprint=_lazy_keyword_fp(spec.keywords),
                    design_fingerprint=f"{spec.niche}:{design_profile.profile_id}",
                )

                self.notifier.send_message(
                    format_ready_message(
                        title=spec.title, quality_score=critique.overall_score,
                        opportunity_score=idea.opportunity_score.weighted_total,
                        design_profile=design_profile.name,
                        files=["XLSX", "PDF", "Preview", "Instructions", "ZIP"],
                    )
                )
                return record

            revision_count += 1
            if revision_count > self.max_revisions:
                record.quality_score = critique.overall_score
                self.repo.save(record)
                self.notifier.send_message(
                    f"<b>NEEDS_REVIEW</b>\nProduct: {spec.title}\n"
                    f"Quality stayed below threshold after {self.max_revisions} revisions "
                    f"(final score: {critique.overall_score}/100)."
                )
                record = self.repo.fail(record.product_id, actor="system", reason="max_revisions_exceeded_needs_review")
                return record

            record.revision_count = revision_count
            self.repo.save(record)
            record = self.repo.transition(record.product_id, ProductState.REVISION, actor="system", reason=f"revision_{revision_count}")
            record = self.repo.transition(record.product_id, ProductState.GENERATING, actor="system", reason="retry_generation")
            # Loop retries generation. In this MVP, revision means
            # re-running generation as-is (deterministic generators
            # produce the same structurally-valid output); a future
            # iteration could mutate spec/design here based on
            # critique.dimension_scores before retrying.


def _json_dumps(payload: dict) -> str:
    import json
    return json.dumps(payload, ensure_ascii=False)


def _lazy_title_fp(title: str) -> str:
    from src.memory.similarity import title_fingerprint
    return title_fingerprint(title)


def _lazy_feature_fp(features: list[str]) -> str:
    from src.memory.similarity import feature_fingerprint
    return feature_fingerprint(features)


def _lazy_keyword_fp(keywords: list[str]) -> str:
    from src.memory.similarity import keyword_fingerprint
    return keyword_fingerprint(keywords)
        
