"""
State machine for a single product's lifecycle.

This module is intentionally storage-agnostic: it operates on a
ProductRecord it is given and returns the updated record plus a
TransitionLogEntry to persist. The actual DB write happens in
memory/product_repository.py — this keeps the state machine unit-testable
without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.core.models import ProductRecord, ProductState, ALLOWED_TRANSITIONS, now_iso


class IllegalTransitionError(Exception):
    """Raised when a transition is not present in ALLOWED_TRANSITIONS."""


class StaleApprovalError(Exception):
    """Raised when an approve/reject action targets a product that is no
    longer WAITING_APPROVAL, or whose run_id does not match the action's
    expected run_id. This is the guard required for requirement #7: a
    late or mismatched APPROVE/REJECT must be a safe no-op from the
    caller's point of view, but the caller needs to know why."""

    def __init__(self, product_id: str, expected_run_id: str, record: ProductRecord):
        self.product_id = product_id
        self.expected_run_id = expected_run_id
        self.record = record
        super().__init__(
            f"Stale/mismatched approval action for product {product_id}: "
            f"expected_run_id={expected_run_id!r}, "
            f"actual_state={record.current_state.value!r}, "
            f"actual_run_id={record.run_id!r}"
        )


@dataclass
class TransitionLogEntry:
    product_id: str
    from_state: Optional[str]
    to_state: str
    actor: str
    reason: str
    created_at: str


class StateMachine:
    """Pure logic for validating and applying state transitions."""

    @staticmethod
    def transition(
        record: ProductRecord,
        to_state: ProductState,
        actor: str,
        reason: str = "",
    ) -> tuple[ProductRecord, TransitionLogEntry]:
        from_state = record.current_state
        legal_targets = ALLOWED_TRANSITIONS.get(from_state, set())
        if to_state not in legal_targets:
            raise IllegalTransitionError(
                f"Illegal transition for product {record.product_id}: "
                f"{from_state.value} -> {to_state.value} is not allowed "
                f"(actor={actor!r}, reason={reason!r})"
            )

        record.current_state = to_state
        record.updated_at = now_iso()

        log_entry = TransitionLogEntry(
            product_id=record.product_id,
            from_state=from_state.value,
            to_state=to_state.value,
            actor=actor,
            reason=reason,
            created_at=record.updated_at,
        )
        return record, log_entry

    @staticmethod
    def approve(
        record: ProductRecord,
        expected_run_id: str,
        actor: str,
    ) -> tuple[ProductRecord, TransitionLogEntry]:
        """Handle a Telegram APPROVE action. Requirement #7: reject stale
        or mismatched approvals instead of silently acting on them."""
        if record.current_state != ProductState.WAITING_APPROVAL or record.run_id != expected_run_id:
            raise StaleApprovalError(record.product_id, expected_run_id, record)
        return StateMachine.transition(
            record, ProductState.STRATEGIZING, actor=actor, reason="telegram_approve"
        )

    @staticmethod
    def reject(
        record: ProductRecord,
        expected_run_id: str,
        actor: str,
    ) -> tuple[ProductRecord, TransitionLogEntry]:
        """Handle a Telegram REJECT action. Same staleness guard as approve."""
        if record.current_state != ProductState.WAITING_APPROVAL or record.run_id != expected_run_id:
            raise StaleApprovalError(record.product_id, expected_run_id, record)
        return StateMachine.transition(
            record, ProductState.STOPPED, actor=actor, reason="telegram_reject"
        )

    @staticmethod
    def fail(record: ProductRecord, actor: str, reason: str) -> tuple[ProductRecord, TransitionLogEntry]:
        """Force-transition to FAILED from any non-terminal state. This is
        the one transition allowed from every state, so exceptions
        anywhere in the pipeline can always be recorded."""
        if record.current_state in (ProductState.READY, ProductState.FAILED, ProductState.STOPPED):
            raise IllegalTransitionError(
                f"Cannot fail product {record.product_id}: already terminal "
                f"({record.current_state.value})"
            )
        from_state = record.current_state
        record.current_state = ProductState.FAILED
        record.updated_at = now_iso()
        log_entry = TransitionLogEntry(
            product_id=record.product_id,
            from_state=from_state.value,
            to_state=ProductState.FAILED.value,
            actor=actor,
            reason=reason,
            created_at=record.updated_at,
        )
        return record, log_entry

    @staticmethod
    def revision_allowed(record: ProductRecord, max_revisions: int) -> bool:
        return record.revision_count < max_revisions
