"""Tests for the grader: optimal_calc math + report_card assembly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from grader.optimal_calc import analyze
from grader.report_card import build_report
from control.session_state import SessionState


def test_analyze_deal_at_midpoint_splits_surplus():
    a = analyze(20000, 15000, 17500, deal_reached=True)
    assert a.zopa_exists and a.zopa_size == 5000
    assert a.buyer_surplus == 2500 and a.seller_surplus == 2500
    assert a.buyer_left_on_table == 2500 and a.seller_left_on_table == 2500
    assert a.buyer_capture_pct == 50.0 and a.seller_capture_pct == 50.0


def test_analyze_buyer_favorable_price():
    # Price near the seller's floor => buyer captured most of the ZOPA.
    a = analyze(20000, 15000, 15500, deal_reached=True)
    assert a.buyer_surplus == 4500 and a.seller_surplus == 500
    assert a.buyer_capture_pct == 90.0


def test_analyze_no_deal_but_zopa_leaves_everything():
    a = analyze(20000, 15000, None, deal_reached=False)
    assert a.buyer_left_on_table == 5000 and a.seller_left_on_table == 5000


def test_analyze_no_zopa():
    a = analyze(14000, 15000, None, deal_reached=False)
    assert a.zopa_exists is False
    assert "no deal was possible" in a.notes.lower()


def test_build_report_on_finished_session():
    s = SessionState(
        buyer_constraints={"reservation_price": 20000, "opening_offer": 15000},
        seller_constraints={"reservation_price": 15000, "opening_offer": 18750},
        currency="₹", title="Delhi rental",
    )
    for _ in range(60):
        if s.pending_approval:
            s.resolve_approval("approve")
        else:
            s.advance_turn()
        if s.status != "active":
            break
    rc = build_report(s)
    assert rc["status"] == "agreed"
    assert rc["final_price"] is not None
    assert "buyer" in rc["tactics_used"] and "seller" in rc["tactics_used"]
    assert rc["clean"] is True  # no price or leak failures in a clean auto run
    assert set(rc["money_left_on_table"]) == {"buyer", "seller"}
