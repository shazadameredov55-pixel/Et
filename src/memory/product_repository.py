"""
ProductRepository: the only place in the codebase allowed to run SQL
against the `products`, `state_transitions`, `research_signals`, and
`run_locks` tables. Orchestrator, Telegram bot, and CLI all go through
this class so the state machine's invariants (legal transitions, stale
approval rejection) are enforced consistently everywhere.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from src.core.models import ProductRecord, ProductState, now_iso
from src.core.state_machine import StateMachine, TransitionLogEntry, StaleApprovalError, IllegalTransitionError

logger = logging.getLogger(__name__)


class DuplicateRunError(Exception):
    """Raised when a run_id is used a second time (requirement #10:
    running the same workflow trigger twice must not create duplicate
    products or double-process the same idea)."""


class ProductNotFoundError(Exception):
    pass


class ProductRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # ------------------------------------------------------------------
    # Run-lock / duplicate-run guard (requirement #9, #10)
    # ------------------------------------------------------------------

    def acquire_run_lock(self, run_id: str, mode: str) -> None:
        """Register this run_id as in-progress. Raises DuplicateRunError
        if the same run_id was already started — this is what stops a
        re-triggered GitHub Actions run (e.g. a retry) from silently
        creating a second product for the same idea."""
        try:
            self._conn.execute(
                "INSERT INTO run_locks (run_id, mode, started_at) VALUES (?, ?, ?)",
                (run_id, mode, now_iso()),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            raise DuplicateRunError(
                f"run_id '{run_id}' has already been started (mode conflict "
                f"or retry of a completed/in-progress run)."
            ) from e

    def finish_run_lock(self, run_id: str) -> None:
        self._conn.execute(
            "UPDATE run_locks SET finished_at = ? WHERE run_id = ?",
            (now_iso(), run_id),
        )
        self._conn.commit()

    def is_run_finished(self, run_id: str) -> bool:
        row = self._conn.execute(
            "SELECT finished_at FROM run_locks WHERE run_id = ?", (run_id,)
        ).fetchone()
        return bool(row and row["finished_at"])

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, record: ProductRecord) -> ProductRecord:
        row = record.to_row()
        self._conn.execute(
            """
            INSERT INTO products (
                product_id, run_id, title, niche, target_customer, design_profile,
                features_json, keywords_json, opportunity_score, quality_score,
                revision_count, current_state, file_paths_json, price_suggestion,
                created_at, updated_at
            ) VALUES (
                :product_id, :run_id, :title, :niche, :target_customer, :design_profile,
                :features_json, :keywords_json, :opportunity_score, :quality_score,
                :revision_count, :current_state, :file_paths_json, :price_suggestion,
                :created_at, :updated_at
            )
            """,
            row,
        )
        self._conn.commit()
        logger.info("Created product %s (niche=%s, run_id=%s)", record.product_id, record.niche, record.run_id)
        return record

    def get(self, product_id: str) -> ProductRecord:
        row = self._conn.execute(
            "SELECT * FROM products WHERE product_id = ?", (product_id,)
        ).fetchone()
        if row is None:
            raise ProductNotFoundError(f"No product with id '{product_id}'")
        return ProductRecord.from_row(dict(row))

    def get_by_run_id(self, run_id: str) -> list[ProductRecord]:
        rows = self._conn.execute(
            "SELECT * FROM products WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [ProductRecord.from_row(dict(r)) for r in rows]

    def save(self, record: ProductRecord) -> None:
        """Persist a full update to an existing record (used after the
        state machine mutates it in place)."""
        row = record.to_row()
        self._conn.execute(
            """
            UPDATE products SET
                title = :title, target_customer = :target_customer,
                design_profile = :design_profile, features_json = :features_json,
                keywords_json = :keywords_json, opportunity_score = :opportunity_score,
                quality_score = :quality_score, revision_count = :revision_count,
                current_state = :current_state, file_paths_json = :file_paths_json,
                price_suggestion = :price_suggestion, updated_at = :updated_at
            WHERE product_id = :product_id
            """,
            row,
        )
        self._conn.commit()

    def _log_transition(self, entry: TransitionLogEntry) -> None:
        self._conn.execute(
            """
            INSERT INTO state_transitions (product_id, from_state, to_state, actor, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry.product_id, entry.from_state, entry.to_state, entry.actor, entry.reason, entry.created_at),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # State-machine-integrated transitions
    # ------------------------------------------------------------------

    def transition(
        self, product_id: str, to_state: ProductState, actor: str, reason: str = ""
    ) -> ProductRecord:
        """Apply a state transition and persist both the updated record
        and the audit log entry atomically (best-effort — SQLite autocommit
        per statement here, acceptable for single-writer GitHub Actions use)."""
        record = self.get(product_id)
        record, log_entry = StateMachine.transition(record, to_state, actor=actor, reason=reason)
        self.save(record)
        self._log_transition(log_entry)
        return record

    def approve(self, product_id: str, expected_run_id: str, actor: str) -> ProductRecord:
        record = self.get(product_id)
        try:
            record, log_entry = StateMachine.approve(record, expected_run_id, actor=actor)
        except StaleApprovalError:
            logger.warning(
                "Ignored stale/mismatched APPROVE for product %s (expected_run_id=%s)",
                product_id, expected_run_id,
            )
            raise
        self.save(record)
        self._log_transition(log_entry)
        return record

    def reject(self, product_id: str, expected_run_id: str, actor: str) -> ProductRecord:
        record = self.get(product_id)
        try:
            record, log_entry = StateMachine.reject(record, expected_run_id, actor=actor)
        except StaleApprovalError:
            logger.warning(
                "Ignored stale/mismatched REJECT for product %s (expected_run_id=%s)",
                product_id, expected_run_id,
            )
            raise
        self.save(record)
        self._log_transition(log_entry)
        return record

    def fail(self, product_id: str, actor: str, reason: str) -> ProductRecord:
        record = self.get(product_id)
        try:
            record, log_entry = StateMachine.fail(record, actor=actor, reason=reason)
        except IllegalTransitionError:
            logger.warning("Product %s already terminal; fail() is a no-op", product_id)
            return record
        self.save(record)
        self._log_transition(log_entry)
        return record

    # ------------------------------------------------------------------
    # Queries used by Telegram /history, /report, and orchestrator resume
    # ------------------------------------------------------------------

    def list_by_state(self, state: ProductState, limit: int = 20) -> list[ProductRecord]:
        rows = self._conn.execute(
            "SELECT * FROM products WHERE current_state = ? ORDER BY updated_at DESC LIMIT ?",
            (state.value, limit),
        ).fetchall()
        return [ProductRecord.from_row(dict(r)) for r in rows]

    def list_incomplete(self) -> list[ProductRecord]:
        """Products not in a terminal state — used to resume work after a
        workflow restart (requirement #11)."""
        terminal = (ProductState.READY.value, ProductState.FAILED.value, ProductState.STOPPED.value)
        placeholders = ",".join("?" for _ in terminal)
        rows = self._conn.execute(
            f"SELECT * FROM products WHERE current_state NOT IN ({placeholders}) ORDER BY created_at",
            terminal,
        ).fetchall()
        return [ProductRecord.from_row(dict(r)) for r in rows]

    def recent(self, limit: int = 10) -> list[ProductRecord]:
        rows = self._conn.execute(
            "SELECT * FROM products ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [ProductRecord.from_row(dict(r)) for r in rows]

    def all_for_similarity(self) -> list[ProductRecord]:
        """All products regardless of state, for similarity comparison —
        even a FAILED or STOPPED product's idea shouldn't be re-proposed
        identically."""
        rows = self._conn.execute("SELECT * FROM products").fetchall()
        return [ProductRecord.from_row(dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # /report stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        total_products = self._conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        by_state_rows = self._conn.execute(
            "SELECT current_state, COUNT(*) AS c FROM products GROUP BY current_state"
        ).fetchall()
        by_state = {r["current_state"]: r["c"] for r in by_state_rows}

        avg_quality_row = self._conn.execute(
            "SELECT AVG(quality_score) AS avg_q FROM products WHERE quality_score IS NOT NULL"
        ).fetchone()
        best_opportunity_row = self._conn.execute(
            "SELECT MAX(opportunity_score) AS best_o FROM products"
        ).fetchone()
        total_revisions_row = self._conn.execute(
            "SELECT SUM(revision_count) AS total_rev FROM products"
        ).fetchone()
        research_runs_row = self._conn.execute(
            "SELECT COUNT(DISTINCT run_id) AS c FROM research_signals"
        ).fetchone()

        return {
            "total_products": total_products,
            "by_state": by_state,
            "successful_products": by_state.get(ProductState.READY.value, 0),
            "failed_runs": by_state.get(ProductState.FAILED.value, 0),
            "average_quality_score": round(avg_quality_row["avg_q"], 1) if avg_quality_row["avg_q"] is not None else None,
            "best_opportunity_score": best_opportunity_row["best_o"],
            "total_revisions": total_revisions_row["total_rev"] or 0,
            "research_runs": research_runs_row["c"],
        }

    # ------------------------------------------------------------------
    # Research signal logging
    # ------------------------------------------------------------------

    def record_research_signal(
        self, run_id: str, source_name: str, niche: str, signal_type: str, payload_json: str
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO research_signals (run_id, source_name, niche, signal_type, payload_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, source_name, niche, signal_type, payload_json, now_iso()),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Similarity fingerprints (requirement #13: persist what similarity.py
    # computes so future runs can compare against history without
    # recomputing fingerprints for every past product on every check)
    # ------------------------------------------------------------------

    def save_similarity_fingerprint(
        self,
        product_id: str,
        title_fingerprint: str,
        feature_fingerprint: str,
        keyword_fingerprint: str,
        design_fingerprint: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO similarity_index (product_id, title_fingerprint, feature_fingerprint, keyword_fingerprint, design_fingerprint)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                title_fingerprint = excluded.title_fingerprint,
                feature_fingerprint = excluded.feature_fingerprint,
                keyword_fingerprint = excluded.keyword_fingerprint,
                design_fingerprint = excluded.design_fingerprint
            """,
            (product_id, title_fingerprint, feature_fingerprint, keyword_fingerprint, design_fingerprint),
        )
        self._conn.commit()

    def get_similarity_fingerprint(self, product_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM similarity_index WHERE product_id = ?", (product_id,)
        ).fetchone()
        return dict(row) if row else None
