"""
db.py — thin SQLite persistence layer (stdlib sqlite3, no ORM).

The live negotiation lives in memory; these helpers snapshot it durably so a
session can be reloaded/audited after a restart. Everything is best-effort:
persistence never blocks or breaks a negotiation.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import time
from pathlib import Path

from config import DB_PATH, SCHEMA_PATH

logger = logging.getLogger("dealbench.db")

# Effective DB path — may be redirected to a temp file if the configured
# location can't be locked (some mounted/networked filesystems reject SQLite
# locking with a "disk I/O error"). Persistence is best-effort, never fatal.
_DB_PATH = str(DB_PATH)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    global _DB_PATH
    schema = Path(SCHEMA_PATH).read_text(encoding="utf-8")
    try:
        Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        with get_conn() as conn:
            conn.executescript(schema)
    except sqlite3.OperationalError as e:
        # Fall back to a temp file on local disk so the app still runs.
        fallback = str(Path(tempfile.gettempdir()) / "dealbench.db")
        logger.warning("DB at %s unusable (%s); falling back to %s", _DB_PATH, e, fallback)
        _DB_PATH = fallback
        with get_conn() as conn:
            conn.executescript(schema)


def db_path() -> str:
    """The path actually in use (post-fallback)."""
    return _DB_PATH


def insert_session(session) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO sessions
               (id, title, currency, buyer_constraints, seller_constraints,
                seller_reservation_price, buyer_reservation_price, deadline_round,
                status, final_price, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (session.id, session.title, session.currency,
             json.dumps(session.buyer_constraints), json.dumps(session.seller_constraints),
             session.seller_reservation, session.buyer_reservation, session.deadline_round,
             session.status, session.final_price, session.created_at),
        )


def update_session_status(session_id: str, status: str, final_price: float | None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET status=?, final_price=? WHERE id=?",
                     (status, final_price, session_id))


def insert_message(session_id: str, m) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO messages
               (session_id, round, side, source, content, quoted_price,
                detected_tactic, tactic_confidence, validator_price_ok,
                validator_leak_detected, backend, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session_id, m.round, m.side, m.source, m.content, m.quoted_price,
             m.detected_tactic, m.tactic_confidence, int(m.validator_price_ok),
             int(m.validator_leak_detected), m.backend, m.timestamp),
        )


def insert_intervention(session_id: str, side: str, action: str, round_num: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO interventions (session_id, side, action, round, timestamp)
               VALUES (?,?,?,?,?)""",
            (session_id, side, action, round_num, time.time()),
        )


def fetch_session(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        msgs = conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
        return {"session": dict(row), "messages": [dict(m) for m in msgs]}
