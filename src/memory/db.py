"""
SQLite schema and connection management for product memory.

Schema matches the design agreed in Phase 1 (products, state_transitions,
similarity_index, research_signals, run_locks). This module owns table
creation only — CRUD and business logic live in product_repository.py and
similarity.py so this file stays trivially reviewable.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id       TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL,
    title            TEXT,
    niche            TEXT NOT NULL,
    target_customer  TEXT,
    design_profile   TEXT,
    features_json    TEXT,
    keywords_json    TEXT,
    opportunity_score REAL,
    quality_score     REAL,
    revision_count    INTEGER DEFAULT 0,
    current_state     TEXT NOT NULL,
    file_paths_json   TEXT,
    price_suggestion  REAL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE(run_id, niche)
);

CREATE TABLE IF NOT EXISTS state_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    from_state TEXT,
    to_state   TEXT NOT NULL,
    actor      TEXT,
    reason     TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS similarity_index (
    product_id TEXT PRIMARY KEY,
    title_fingerprint   TEXT,
    feature_fingerprint TEXT,
    keyword_fingerprint TEXT,
    design_fingerprint  TEXT,
    FOREIGN KEY(product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS research_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    niche TEXT NOT NULL,
    signal_type TEXT,
    payload_json TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_locks (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_products_state ON products(current_state);
CREATE INDEX IF NOT EXISTS idx_products_run_id ON products(run_id);
CREATE INDEX IF NOT EXISTS idx_state_transitions_product ON state_transitions(product_id);
CREATE INDEX IF NOT EXISTS idx_research_signals_run ON research_signals(run_id);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open (and if needed create) the SQLite database at db_path with
    sane defaults: row access by column name, foreign keys enforced."""
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables/indexes if they do not already exist, and record
    the schema version. Idempotent — safe to call on every workflow run
    after restoring the DB artifact."""
    conn.executescript(_SCHEMA_SQL)
    row = conn.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_meta (id, version) VALUES (1, ?)", (SCHEMA_VERSION,))
        logger.info("Initialized new product-memory database, schema version %s", SCHEMA_VERSION)
    elif row["version"] != SCHEMA_VERSION:
        # MVP: no automatic migrations between versions yet. Fail loudly
        # rather than silently operating on a mismatched schema.
        raise RuntimeError(
            f"Database schema version {row['version']} does not match "
            f"expected {SCHEMA_VERSION}. A migration step is required "
            f"before this code can run against this database."
        )
    conn.commit()


@contextmanager
def open_db(db_path: str) -> Iterator[sqlite3.Connection]:
    """Convenience context manager: open, initialize, yield, close."""
    conn = get_connection(db_path)
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()
