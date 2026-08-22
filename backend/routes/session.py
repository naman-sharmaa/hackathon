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

import catalog
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
    """Create a new negotiation.

    Two modes:
      * Bound to a listing — pass ``property_id``; the seller's floor/ask come
        from the catalog and the buyer's budget defaults to the asking price
        (so a deal is always reachable). This is what the contractor site uses.
      * Bare — pass explicit ``buyer``/``seller`` constraints (the original
        abstract negotiation); sensible defaults let a judge quick-start.

    Also accepts:
      * ``buyer_control``: "autopilot" (default) or "manual".
      * ``budget_cap``: soft approval ceiling for the buyer's agent.
    """
    prop_public = None
    pid = body.get("property_id")
    if pid:
        raw = catalog.get(pid)
        if raw is None:
            return 400, {"error": f"unknown property_id {pid!r}"}
        prop_public = catalog.public(raw)
        seller = {
            "reservation_price": float(raw["floor_price"]),   # PRIVATE floor
            "opening_offer": float(raw["asking_price"]),       # public ask = anchor
            "persona": (f"You represent the contractor selling {raw['address']} "
                        f"— a {raw['sqft']} sqft {raw['type'].lower()}, "
                        f"{raw['beds']} bed / {raw['baths']} bath, listed at "
                        f"${raw['asking_price']:,.0f}. You are proud of the build."),
        }
        raw_buyer = body.get("buyer") or {}
        budget = raw_buyer.get("reservation_price", raw["asking_price"])
        buyer = {
            "reservation_price": float(budget),
            "opening_offer": raw_buyer.get("opening_offer"),
            "persona": raw_buyer.get("persona", ""),
        }
        title = body.get("title") or f"Offer on {raw['address']}"
    else:
        buyer = _constraints(body, "buyer", 20000.0)
        seller = _constraints(body, "seller", 15000.0)
        title = body.get("title", "Untitled negotiation")

    try:
        session = SessionState(
            buyer_constraints=buyer,
            seller_constraints=seller,
            currency=body.get("currency", "$"),
            deadline_round=body.get("deadline_round"),
            tolerance=body.get("tolerance"),
            max_rounds=body.get("max_rounds"),
            title=title,
            property=prop_public,
            buyer_control=body.get("buyer_control", "autopilot"),
            budget_cap=body.get("budget_cap"),
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

    If the buyer is on autopilot and its move needs human approval, this returns
    with ``awaiting_approval`` set and does NOT advance — resolve it via
    POST /session/{id}/approve.
    """
    session = store.get(params["id"])
    if session is None:
        return 404, {"error": "session not found"}
    if session.status != "active":
        return 409, {"error": "session already ended", "status": session.status,
                     "session": session.to_public_dict()}
    if session.pending_approval is not None:
        return 409, {"error": "waiting on human approval; use /approve",
                     "awaiting_approval": True,
                     "pending_approval": session.pending_approval,
                     "session": session.to_public_dict()}

    human_message = body.get("message")
    produced = []

    result = session.advance_turn(human_message=human_message)
    if "error" in result and not result.get("awaiting_approval"):
        return 400, result
    produced.extend(result.get("messages", []))
    if produced:
        for m in session.history[-len(produced):]:
            _persist_message(session.id, m)

    # If a human just spoke, let the contractor (auto) reply immediately so the
    # chat feels conversational — a single reply, not a full run.
    if (human_message is not None and session.status == "active"
            and session.pending_approval is None and not body.get("run_to_end")):
        reply = session.maybe_auto_reply()
        if reply:
            produced.extend(reply)
            for m in session.history[-len(reply):]:
                _persist_message(session.id, m)

    # Optional convenience: keep stepping while the next side is on autopilot
    # and no human input / approval is required (great for a one-click demo).
    if body.get("run_to_end") and session.status == "active":
        guard = 0
        while (session.status == "active"
               and session.mode[session.turn] == "auto"
               and session.pending_approval is None
               and guard < session.max_rounds * 2 + 5):
            r = session.advance_turn()
            guard += 1
            if "error" in r and not r.get("awaiting_approval"):
                break
            msgs = r.get("messages", [])
            for m in session.history[-len(msgs):] if msgs else []:
                _persist_message(session.id, m)
            produced.extend(msgs)
            if r.get("awaiting_approval"):
                break

    _persist_status(session)
    return 200, {
        "session_id": session.id,
        "status": session.status,
        "turn": session.turn,
        "offers": dict(session.offer),
        "final_price": session.final_price,
        "awaiting_approval": session.pending_approval is not None,
        "pending_approval": session.pending_approval,
        "awaiting_human": (session.turn if session.mode[session.turn] == "human"
                           and session.status == "active"
                           and session.pending_approval is None else None),
        "new_messages": produced,
        "session": session.to_public_dict(),
    }


def get_session(params, body, query):
    session = store.get(params["id"])
    if session is None:
        return 404, {"error": "session not found"}
    return 200, session.to_public_dict()
