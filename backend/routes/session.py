"""
routes/session.py — create a negotiation and advance it turn-by-turn.

  POST /session                 -> create a session (returns its public state)
  POST /session/{id}/message    -> advance ONE turn; body may carry a human
                                   message (during a takeover) and/or ask to
                                   auto-run to the end.
  GET  /session/{id}            -> current public state (for the live view)

Persistence is best-effort: a DB hiccup never blocks a negotiation.
"""
from __future__ import annotations

import logging

from control.session_state import SessionState
from routes import store

try:
    from db import db
except Exception:  # pragma: no cover - db is optional
    db = None

logger = logging.getLogger("dealbench.routes.session")


def _persist_session(session) -> None:
    if db is None:
        return
    try:
        db.insert_session(session)
    except Exception as e:  # pragma: no cover
        logger.info("session persist skipped: %s", e)


def _persist_message(session_id, m) -> None:
    if db is None:
        return
    try:
        db.insert_message(session_id, m)
    except Exception as e:  # pragma: no cover
        logger.info("message persist skipped: %s", e)


def _persist_status(session) -> None:
    if db is None:
        return
    try:
        db.update_session_status(session.id, session.status, session.final_price)
    except Exception as e:  # pragma: no cover
        logger.info("status persist skipped: %s", e)


def _constraints(body: dict, key: str, default_reservation: float) -> dict:
    raw = body.get(key) or body.get(f"{key}_constraints") or {}
    return {
        "reservation_price": float(raw.get("reservation_price", default_reservation)),
        "opening_offer": raw.get("opening_offer"),
        "persona": raw.get("persona", ""),
    }


def create_session(params, body, query):
    """Create a new negotiation. Sensible defaults let a judge 'quick-start'
    with an empty body and still get a working ZOPA."""
    buyer = _constraints(body, "buyer", 20000.0)
    seller = _constraints(body, "seller", 15000.0)
    try:
        session = SessionState(
            buyer_constraints=buyer,
            seller_constraints=seller,
            currency=body.get("currency", "$"),
            deadline_round=body.get("deadline_round"),
            tolerance=body.get("tolerance"),
            max_rounds=body.get("max_rounds"),
            title=body.get("title", "Untitled negotiation"),
        )
    except (KeyError, ValueError, TypeError) as e:
        return 400, {"error": f"invalid constraints: {e}"}

    store.add(session)
    _persist_session(session)
    return 201, session.to_public_dict()


def post_message(params, body, query):
    """Advance the negotiation. One call = one turn, unless run_to_end=true.

    body:
      { "message": "<human text>" }   # required when the side is in human mode
      { "run_to_end": true }          # auto-play remaining AUTO turns to a stop
    """
    session = store.get(params["id"])
    if session is None:
        return 404, {"error": "session not found"}
    if session.status != "active":
        return 409, {"error": "session already ended", "status": session.status,
                     "session": session.to_public_dict()}

    human_message = body.get("message")
    produced = []

    result = session.advance_turn(human_message=human_message)
    if "error" in result:
        return 400, result
    produced.extend(result.get("messages", []))
    for m in session.history[-len(result.get("messages", [])):]:
        _persist_message(session.id, m)

    # Optional convenience: keep stepping while the next side is on autopilot
    # and no human input is required (great for a one-click demo run).
    if body.get("run_to_end") and session.status == "active":
        guard = 0
        while (session.status == "active"
               and session.mode[session.turn] == "auto" and guard < session.max_rounds * 2 + 5):
            r = session.advance_turn()
            guard += 1
            if "error" in r:
                break
            for m in session.history[-len(r.get("messages", [])):]:
                _persist_message(session.id, m)
            produced.extend(r.get("messages", []))

    _persist_status(session)
    return 200, {
        "session_id": session.id,
        "status": session.status,
        "turn": session.turn,
        "offers": dict(session.offer),
        "final_price": session.final_price,
        "awaiting_human": (session.turn if session.mode[session.turn] == "human"
                           and session.status == "active" else None),
        "new_messages": produced,
        "session": session.to_public_dict(),
    }


def get_session(params, body, query):
    session = store.get(params["id"])
    if session is None:
        return 404, {"error": "session not found"}
    return 200, session.to_public_dict()
