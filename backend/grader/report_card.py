"""
report_card.py — the end-of-negotiation summary (spec Section 9 report page).

Turns a finished (or in-progress) SessionState into a judge-readable card:
outcome, final price, money left on the table per side, tactics used per side,
confidence flags, intervention log, and how much narration degraded to the
fallback. Pure post-processing — no LLM.
"""
from __future__ import annotations

from collections import Counter

from grader.optimal_calc import analyze

LOW_CONFIDENCE = 0.5


def build_report(session) -> dict:
    hist = session.history
    deal_reached = session.status == "agreed"
    deal = analyze(session.buyer_reservation, session.seller_reservation,
                   session.final_price, deal_reached)

    tactics_by_side = {"buyer": Counter(), "seller": Counter()}
    backends = Counter()
    price_failures, leak_failures, low_conf = [], [], []

    for m in hist:
        if m.detected_tactic:
            tactics_by_side[m.side][m.detected_tactic] += 1
        if m.backend:
            backends[m.backend] += 1
        if not m.validator_price_ok:
            price_failures.append(_flag(m, "price mismatch vs engine"))
        if m.validator_leak_detected:
            leak_failures.append(_flag(m, "reservation-price leak"))
        if 0 < m.tactic_confidence < LOW_CONFIDENCE:
            low_conf.append(_flag(m, f"low tactic confidence ({m.tactic_confidence:.2f})"))

    return {
        "session_id": session.id,
        "title": session.title,
        "currency": session.currency,
        "status": session.status,
        "outcome": _outcome_label(session.status),
        "final_price": session.final_price,
        "rounds_completed": session.exchange,
        "deal_analysis": deal.to_dict(),
        "money_left_on_table": {
            "buyer": deal.buyer_left_on_table,
            "seller": deal.seller_left_on_table,
        },
        "tactics_used": {
            "buyer": dict(tactics_by_side["buyer"]),
            "seller": dict(tactics_by_side["seller"]),
        },
        "narration_backends": dict(backends),
        "degraded_to_fallback": bool(any(session.fallback_active.values())
                                      or backends.get("ollama", 0) > 0
                                      or backends.get("mock", 0) > 0),
        "interventions": [
            {"side": i.side, "action": i.action, "round": i.round} for i in session.interventions
        ],
        "confidence_flags": {
            "price_failures": price_failures,
            "leak_failures": leak_failures,
            "low_confidence_tactics": low_conf,
        },
        "clean": not price_failures and not leak_failures,
    }


def _flag(m, reason: str) -> dict:
    return {
        "round": m.round, "side": m.side, "source": m.source,
        "reason": reason,
        "excerpt": (m.content[:80] + "…") if len(m.content) > 80 else m.content,
    }


def _outcome_label(status: str) -> str:
    return {
        "agreed": "Deal agreed",
        "walked_away": "Walked away — no deal",
        "max_rounds": "Hit round cap — no deal",
        "active": "In progress",
    }.get(status, status)
