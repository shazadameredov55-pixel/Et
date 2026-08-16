"""
Core domain models shared across the pipeline. These are plain dataclasses
with (de)serialization helpers — no business logic lives here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# State machine states
# --------------------------------------------------------------------------

class ProductState(str, Enum):
    RESEARCHING = "RESEARCHING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    STRATEGIZING = "STRATEGIZING"
    GENERATING = "GENERATING"
    QUALITY_CHECK = "QUALITY_CHECK"
    REVISION = "REVISION"
    PACKAGING = "PACKAGING"
    READY = "READY"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


# Allowed transitions: from_state -> set of legal to_states.
# Enforced by StateMachine (see state_machine.py). Keeping the table here
# next to ProductState keeps the single source of truth in one place.
ALLOWED_TRANSITIONS: dict[ProductState, set[ProductState]] = {
    ProductState.RESEARCHING: {ProductState.WAITING_APPROVAL, ProductState.FAILED},
    ProductState.WAITING_APPROVAL: {
        ProductState.STRATEGIZING,   # approve
        ProductState.STOPPED,        # reject
        ProductState.FAILED,
    },
    ProductState.STRATEGIZING: {ProductState.GENERATING, ProductState.FAILED},
    ProductState.GENERATING: {ProductState.QUALITY_CHECK, ProductState.FAILED},
    ProductState.QUALITY_CHECK: {
        ProductState.REVISION,
        ProductState.PACKAGING,
        ProductState.FAILED,
    },
    ProductState.REVISION: {ProductState.GENERATING, ProductState.FAILED},
    ProductState.PACKAGING: {ProductState.READY, ProductState.FAILED},
    ProductState.READY: set(),        # terminal
    ProductState.FAILED: set(),       # terminal
    ProductState.STOPPED: set(),      # terminal
}


# --------------------------------------------------------------------------
# Opportunity scoring
# --------------------------------------------------------------------------

@dataclass
class OpportunityScore:
    demand: float
    competition: float           # already inverted upstream: higher = less competition = better
    differentiation: float
    commercial_potential: float
    usability: float
    production_ease: float
    weighted_total: float
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Product idea / spec
# --------------------------------------------------------------------------

@dataclass
class ProductIdea:
    """Output of research + scoring, before strategy/design are applied."""
    idea_id: str
    run_id: str
    niche: str                     # subcategory id, e.g. "debt_payoff_tracker"
    working_title: str
    opportunity_score: OpportunityScore
    supporting_signals_summary: str = ""


@dataclass
class ProductSpec:
    """Output of the ProductStrategist for an approved idea."""
    product_id: str
    run_id: str
    niche: str
    title: str
    target_customer: str
    problem: str
    current_workaround: str
    desired_outcome: str
    core_features: list[str]
    optional_features: list[str]
    differentiation: str
    ux_approach: str
    visual_style_hint: str
    file_formats: list[str] = field(default_factory=lambda: ["xlsx", "csv", "pdf"])
    keywords: list[str] = field(default_factory=list)
    price_suggestion: Optional[float] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class DesignProfile:
    """Concrete design system resolved for a ProductSpec (from
    config/design_profiles.yaml), not a raw color choice."""
    profile_id: str
    name: str
    typography: dict[str, Any]
    spacing: dict[str, Any]
    hierarchy: str
    layout: str
    table_design: dict[str, Any]
    visual_density: str
    icon_usage: str


# --------------------------------------------------------------------------
# Persisted product record (mirrors the `products` DB table)
# --------------------------------------------------------------------------

@dataclass
class ProductRecord:
    product_id: str
    run_id: str
    title: str
    niche: str
    target_customer: str
    design_profile: str
    features: list[str]
    keywords: list[str]
    opportunity_score: float
    quality_score: Optional[float]
    revision_count: int
    current_state: ProductState
    file_paths: list[str]
    price_suggestion: Optional[float]
    created_at: str
    updated_at: str

    @staticmethod
    def new(run_id: str, niche: str) -> "ProductRecord":
        ts = now_iso()
        return ProductRecord(
            product_id=new_id(),
            run_id=run_id,
            title="",
            niche=niche,
            target_customer="",
            design_profile="",
            features=[],
            keywords=[],
            opportunity_score=0.0,
            quality_score=None,
            revision_count=0,
            current_state=ProductState.RESEARCHING,
            file_paths=[],
            price_suggestion=None,
            created_at=ts,
            updated_at=ts,
        )

    def to_row(self) -> dict[str, Any]:
        """Flatten for SQLite storage (JSON-encode list fields)."""
        return {
            "product_id": self.product_id,
            "run_id": self.run_id,
            "title": self.title,
            "niche": self.niche,
            "target_customer": self.target_customer,
            "design_profile": self.design_profile,
            "features_json": json.dumps(self.features, ensure_ascii=False),
            "keywords_json": json.dumps(self.keywords, ensure_ascii=False),
            "opportunity_score": self.opportunity_score,
            "quality_score": self.quality_score,
            "revision_count": self.revision_count,
            "current_state": self.current_state.value,
            "file_paths_json": json.dumps(self.file_paths, ensure_ascii=False),
            "price_suggestion": self.price_suggestion,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_row(row: dict[str, Any]) -> "ProductRecord":
        return ProductRecord(
            product_id=row["product_id"],
            run_id=row["run_id"],
            title=row["title"] or "",
            niche=row["niche"],
            target_customer=row["target_customer"] or "",
            design_profile=row["design_profile"] or "",
            features=json.loads(row["features_json"] or "[]"),
            keywords=json.loads(row["keywords_json"] or "[]"),
            opportunity_score=row["opportunity_score"] or 0.0,
            quality_score=row["quality_score"],
            revision_count=row["revision_count"] or 0,
            current_state=ProductState(row["current_state"]),
            file_paths=json.loads(row["file_paths_json"] or "[]"),
            price_suggestion=row["price_suggestion"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# --------------------------------------------------------------------------
# Quality control
# --------------------------------------------------------------------------

@dataclass
class QCIssue:
    severity: str          # "critical" | "major" | "minor"
    code: str
    message: str


@dataclass
class QCResult:
    score: float            # 0-100
    passed: bool
    issues: list[QCIssue]
    checked_files: list[str]
