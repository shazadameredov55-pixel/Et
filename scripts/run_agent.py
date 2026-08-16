#!/usr/bin/env python3
"""
Entry point invoked by .github/workflows/run_agent.yml. Translates
workflow_dispatch inputs into an Orchestrator call and exits non-zero on
failure so the Actions run is visibly marked failed (requirement #19:
no silent failure).

Usage (matches the workflow's `inputs:`):
    python scripts/run_agent.py --mode research --category personal-finance
    python scripts/run_agent.py --mode produce --product-id <id> --run-id <id>
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.orchestrator import Orchestrator
from src.core.state_machine import StaleApprovalError
from src.memory.product_repository import DuplicateRunError
from src.generators.blueprints import available_niches

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Digital Product Agent runner")
    parser.add_argument("--mode", required=True, choices=["research", "produce"])
    parser.add_argument("--category", default="personal-finance")
    parser.add_argument("--research-depth", default="standard", choices=["quick", "standard", "deep"])
    parser.add_argument("--product-mode", default="single", choices=["single"])
    parser.add_argument("--quality-threshold", type=float, default=80.0)
    parser.add_argument("--product-id", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--db-path", default="data/products.db")
    parser.add_argument("--output-dir", default="output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id or f"{os.environ.get('GITHUB_RUN_ID', 'local')}-{uuid.uuid4().hex[:8]}"

    orch = Orchestrator(db_path=args.db_path, output_dir=args.output_dir)
    try:
        if args.mode == "research":
            # research_depth currently controls how many niches are
            # scanned per run; "deep" scans every registered niche,
            # "standard" scans a representative subset, "quick" scans one.
            niches = available_niches()
            if args.research_depth == "quick":
                niches = niches[:1]
            elif args.research_depth == "standard":
                niches = niches[: max(1, len(niches) // 2 + 1)]
            # "deep" uses the full list as-is.

            logger.info("Running research (run_id=%s, niches=%s)", run_id, niches)
            try:
                record = orch.run_research(run_id=run_id, category_niches=niches)
            except DuplicateRunError as e:
                logger.error("Duplicate run_id: %s", e)
                return 1

            if record is None:
                logger.info("No opportunity cleared the notify threshold this run.")
            else:
                logger.info("Sent product %s for approval (state=%s)", record.product_id, record.current_state.value)
            return 0

        else:  # produce
            if not args.product_id or not args.run_id:
                logger.error("--product-id and --run-id are required for mode=produce")
                return 1
            logger.info("Running produce for product_id=%s, run_id=%s", args.product_id, args.run_id)
            try:
                record = orch.run_produce(args.product_id, expected_run_id=args.run_id)
            except StaleApprovalError as e:
                logger.error("Stale/mismatched approval: %s", e)
                return 1
            logger.info("Production finished: product %s -> %s", record.product_id, record.current_state.value)
            return 0 if record.current_state.value == "READY" else 1
    finally:
        orch.close()


if __name__ == "__main__":
    sys.exit(main())
