"""
routes/approve.py — the human-in-the-loop decision endpoint.

When the buyer is on autopilot and its next move trips an approval gate
(closing the deal, the contractor pressing hard, or exceeding your budget cap),
the negotiation STOPS with a `pending_approval`. This endpoint is how the human
resolves it:

  POST /session/{id}/approve
    { "decision": "approve" }                  -> let the agent make the move
    { "decision": "counter", "message": "..."} -> take over and send it yourself
    { "decision": "walk" }                     -> decline and end the negotiation

The heavy lifting is in control/session_state.resolve_approval; this is the HTTP
skin plus best-effort persistence and the immediate contractor reply.
"""
from __future__ import annotations

import logging

from routes import store

try:
    from db import db
except Exception:  # pragma: no cover
    db = None

logger = logging.getLogger("dealbench.routes.approve")

_VALID = {"approve", "accept", "yes", "counter", "take_over", "intervene",
          "myself", "walk", "walk_away", "decline", "reject", "no"}


def _persist_message(session_id, m) -> None:
    if db is None:
        return
    try:
        db.insert_message(session_id, m)
    except Exception as e:  # pragma: no cover
        logger.info("message persist skipped: %s", e)


def approve(params, body, query):
    session = store.get(params["id"])
    if session is None:
        return 404, {"error": "session not found"}
    if session.status != "active":
        return 409, {"error": "session already ended", "status": session.status,
                     "session": session.to_public_dict()}
    if session.pending_approval is None:
        return 409, {"error": "no pending approval on this session",
                     "session": session.to_public_dict()}

    decision = (body.get("decision") or "").lower()
    if decision not in _VALID:
        return 400, {"error": f"decision must be one of approve / counter / walk"}

    result = session.resolve_approval(decision, message=body.get("message"))
    if "error" in result:
        return 400, {**result, "session": session.to_public_dict()}

    produced = list(result.get("messages", []))

    # After an approved/countered buyer move, let the contractor reply at once
    # so the transcript reads naturally (unless we've closed or hit a new gate).
    if session.status == "active" and session.pending_approval is None:
        produced.extend(session.maybe_auto_reply())

    # Best-effort persistence of everything appended this call.
    if produced:
        for m in session.history[-len(produced):]:
            _persist_message(session.id, m)
    if db is not None:
        try:
            db.update_session_status(session.id, session.status, session.final_price)
        except Exception as e:  # pragma: no cover
            logger.info("status persist skipped: %s", e)

    return 200, {
        "session_id": session.id,
        "status": session.status,
        "turn": session.turn,
        "offers": dict(session.offer),
        "final_price": session.final_price,
        "decision": decision,
        "new_messages": produced,
        "awaiting_approval": session.pending_approval is not None,
        "pending_approval": session.pending_approval,
        "awaiting_human": (session.turn if session.mode[session.turn] == "human"
                           and session.status == "active"
                           and session.pending_approval is None else None),
        "session": session.to_public_dict(),
    }
