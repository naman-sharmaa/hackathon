"""
routes/intervene.py — human take-over / return-to-AI for either side.

  POST /session/{id}/intervene   body: {"side": "buyer"|"seller",
                                         "action": "take_over"|"return_to_ai"}

The heavy lifting lives in control/intervention.py; this is just the HTTP skin.
"""
from __future__ import annotations

import logging

from control.intervention import apply_intervention, TAKE_OVER, RETURN_TO_AI
from routes import store

try:
    from db import db
except Exception:  # pragma: no cover
    db = None

logger = logging.getLogger("dealbench.routes.intervene")


def intervene(params, body, query):
    session = store.get(params["id"])
    if session is None:
        return 404, {"error": "session not found"}

    side = body.get("side")
    action = body.get("action")
    if action not in (TAKE_OVER, RETURN_TO_AI):
        return 400, {"error": f"action must be {TAKE_OVER!r} or {RETURN_TO_AI!r}"}

    result = apply_intervention(session, side, action)
    if "error" in result:
        return 400, result

    if db is not None:
        try:
            db.insert_intervention(session.id, side, action, session.exchange)
        except Exception as e:  # pragma: no cover
            logger.info("intervention persist skipped: %s", e)

    result["session"] = session.to_public_dict()
    return 200, result
