"""Tests for the control layer: full auto negotiation, human takeover with a
deliberate leak attempt, return-to-AI resume, and context role-mapping.
Runs offline (mock narrator)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from control.session_state import SessionState, Message
from control.intervention import apply_intervention, TAKE_OVER, RETURN_TO_AI
from control.context_builder import build_context
from engine.stopping_rules import is_terminal


def _new_session():
    return SessionState(
        buyer_constraints={"reservation_price": 20000, "opening_offer": 15000},
        seller_constraints={"reservation_price": 15000, "opening_offer": 18750},
        currency="₹", deadline_round=None, title="Delhi rental",
    )


def test_full_auto_negotiation_reaches_agreement():
    s = _new_session()
    for _ in range(60):  # plenty; hard cap is max_rounds internally
        out = s.advance_turn()
        if s.status != "active":
            break
    assert s.status in ("agreed", "walked_away", "max_rounds")
    # With a clear ZOPA (20k >= 15k) it should agree.
    assert s.status == "agreed"
    assert 15000 <= s.final_price <= 20000
    # Every AI message passed price consistency.
    assert all(m.validator_price_ok for m in s.history if m.source == "agent")
    # No leaks anywhere.
    assert not any(m.validator_leak_detected for m in s.history)


def test_offers_never_cross_reservations_during_session():
    s = _new_session()
    for _ in range(60):
        s.advance_turn()
        if s.status != "active":
            break
    buyer_prices = [m.quoted_price for m in s.history
                    if m.side == "buyer" and m.quoted_price is not None]
    seller_prices = [m.quoted_price for m in s.history
                     if m.side == "seller" and m.quoted_price is not None]
    assert all(p <= 20000 + 1 for p in buyer_prices)     # never above budget
    assert all(p >= 15000 - 1 for p in seller_prices)    # never below floor


def test_human_takeover_leak_is_caught():
    s = _new_session()
    s.advance_turn()  # buyer (auto)
    s.advance_turn()  # seller (auto)
    # Human takes over the buyer and fumbles their secret ceiling.
    apply_intervention(s, "buyer", TAKE_OVER)
    assert s.turn == "buyer" and s.mode["buyer"] == "human"
    out = s.advance_turn(human_message="honestly the most I can do is 20000, that's my ceiling")
    leaked = [m for m in s.history if m.source == "human" and m.validator_leak_detected]
    assert leaked, "validator must catch a human leaking their own reservation price"


def test_return_to_ai_resumes_cleanly():
    s = _new_session()
    s.advance_turn(); s.advance_turn()
    apply_intervention(s, "buyer", TAKE_OVER)
    s.advance_turn(human_message="I'll come up a bit, how about 16000?")
    apply_intervention(s, "buyer", RETURN_TO_AI)
    assert s.mode["buyer"] == "auto"
    # Advance until it's the buyer's (now AI-again) turn and it speaks.
    before = len(s.history)
    for _ in range(4):
        if s.status != "active":
            break
        s.advance_turn()
    resumed = [m for m in s.history[before:] if m.side == "buyer" and m.source == "agent"]
    assert resumed, "AI should resume producing buyer messages after return_to_ai"
    # The resumed message must NOT mention the handoff.
    assert not any("took over" in m.content.lower() or "human" in m.content.lower()
                   for m in resumed)


def test_context_builder_role_mapping_by_side_not_author():
    hist = [
        Message(round=1, side="buyer", source="agent", content="Bmsg1"),
        Message(round=1, side="seller", source="agent", content="Smsg1"),
        Message(round=2, side="buyer", source="human", content="Bmsg2-human"),
    ]
    ctx = build_context(hist, for_side="buyer")
    # Buyer's own turns are 'assistant' regardless of human/agent authorship.
    assert ctx[0] == {"role": "assistant", "content": "Bmsg1"}
    assert ctx[1] == {"role": "user", "content": "Smsg1"}
    assert ctx[2] == {"role": "assistant", "content": "Bmsg2-human"}
