"""
routes/store.py — process-wide, in-memory registry of live negotiations.

The authoritative negotiation state lives here (an object graph is far richer
than a DB row); SQLite is a best-effort durable snapshot on the side. A single
HTTPServer instance is single-threaded, so a plain dict is safe.
"""
from __future__ import annotations

from control.session_state import SessionState

SESSIONS: dict[str, SessionState] = {}


def add(session: SessionState) -> None:
    SESSIONS[session.id] = session


def get(session_id: str) -> SessionState | None:
    return SESSIONS.get(session_id)


def exists(session_id: str) -> bool:
    return session_id in SESSIONS
