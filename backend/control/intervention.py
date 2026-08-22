"""
intervention.py — human take-over / return-to-AI, sitting AROUND the agents.

Taking over the Buyer just means the next Buyer message comes from a text box
instead of buyer_agent. The engine, validator, and stopping rules apply
identically either way — which is exactly why returning control to the AI
"just works" (see context_builder.py). No negotiation state is discarded on a
mode flip.
"""
from __future__ import annotations

from control.session_state import SessionState, Intervention

TAKE_OVER = "take_over"
RETURN_TO_AI = "return_to_ai"


def apply_intervention(session: SessionState, side: str, action: str) -> dict:
    if side not in ("buyer", "seller"):
        return {"error": f"invalid side {side!r}"}
    if action == TAKE_OVER:
        session.mode[side] = "human"
    elif action == RETURN_TO_AI:
        session.mode[side] = "auto"
        # If a human returns control, re-arm the primary agent unless the
        # circuit breaker is still open (then it stays on the fallback agent).
        if not session.client.breakers[side].is_open and session.fallback_active[side]:
            from agents.buyer_agent import BuyerAgent
            from agents.seller_agent import SellerAgent
            session.fallback_active[side] = False
            cls = BuyerAgent if side == "buyer" else SellerAgent
            persona = (session.buyer_constraints if side == "buyer"
                       else session.seller_constraints).get("persona", "")
            session.agents[side] = cls(session.client, currency=session.currency,
                                       persona_extra=persona)
    else:
        return {"error": f"invalid action {action!r}"}

    rec = Intervention(side=side, action=action, round=session.exchange)
    session.interventions.append(rec)
    return {
        "session_id": session.id,
        "side": side,
        "action": action,
        "mode": dict(session.mode),
        "awaiting_human": (session.turn if session.mode[session.turn] == "human"
                           and session.status == "active" else None),
    }
