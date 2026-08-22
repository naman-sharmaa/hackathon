"""
Unit tests for the deterministic concession engine.

These run with NO API key and NO network — proving the deal math is correct in
isolation before any agent/LLM code exists (spec Section 11, step 2).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_tests import assert_raises
from engine.concession_engine import (
    next_offer, opening_offer, has_zopa, _conceded_fraction,
)

BUYER_RES = 20000.0   # buyer's max budget
SELLER_RES = 15000.0  # seller's floor


# --- opening / anchor -------------------------------------------------------

def test_opening_offer_sides():
    # Buyer opens below budget, seller opens above floor.
    assert opening_offer("buyer", 20000) < 20000
    assert opening_offer("seller", 15000) > 15000


def test_round_one_is_the_anchor():
    b = next_offer("buyer", 1, BUYER_RES, None, None, None)
    assert b == opening_offer("buyer", BUYER_RES)
    s = next_offer("seller", 1, SELLER_RES, None, None, None)
    assert s == opening_offer("seller", SELLER_RES)


# --- the core invariant: never cross your own reservation -------------------

def test_buyer_never_exceeds_budget():
    for r in range(1, 40):
        assert next_offer("buyer", r, BUYER_RES, None, None, None) <= BUYER_RES + 1e-6


def test_seller_never_below_floor():
    for r in range(1, 40):
        assert next_offer("seller", r, SELLER_RES, None, None, None) >= SELLER_RES - 1e-6


def test_reservation_never_crossed_even_with_aggressive_tactic():
    # A walk-away threat concedes MORE, but still must not cross reservation.
    for r in range(1, 40):
        b = next_offer("buyer", r, BUYER_RES, None, "walk_away_threat", None)
        s = next_offer("seller", r, SELLER_RES, None, "walk_away_threat", None)
        assert b <= BUYER_RES + 1e-6
        assert s >= SELLER_RES - 1e-6


# --- monotonic concession (base curve, no counterparty cap) -----------------

def test_buyer_offers_rise_monotonically():
    prev = -1
    for r in range(1, 25):
        cur = next_offer("buyer", r, BUYER_RES, None, None, None)
        assert cur >= prev
        prev = cur


def test_seller_offers_fall_monotonically():
    prev = float("inf")
    for r in range(1, 25):
        cur = next_offer("seller", r, SELLER_RES, None, None, None)
        assert cur <= prev
        prev = cur


# --- diminishing steps (feels human, not linear) ----------------------------

def test_concession_steps_shrink():
    steps = []
    prev = next_offer("buyer", 1, BUYER_RES, None, None, None)
    for r in range(2, 12):
        cur = next_offer("buyer", r, BUYER_RES, None, None, None)
        steps.append(round(cur - prev, 4))
        prev = cur
    # Each successive step is <= the previous one (allowing tiny float noise).
    for earlier, later in zip(steps, steps[1:]):
        assert later <= earlier + 1e-6


def test_conceded_fraction_starts_zero_and_grows():
    assert _conceded_fraction(1, 0.8) == 0.0
    assert 0 < _conceded_fraction(2, 0.8) < _conceded_fraction(5, 0.8) < 1.0


# --- no-crossover guard -----------------------------------------------------

def test_buyer_does_not_bid_above_sellers_ask():
    # Seller is currently asking 16000; buyer should never be pushed above it.
    for r in range(1, 30):
        b = next_offer("buyer", r, BUYER_RES, 16000.0, None, None)
        assert b <= 16000.0 + 1e-6


def test_seller_does_not_ask_below_buyers_bid():
    for r in range(1, 30):
        s = next_offer("seller", r, SELLER_RES, 15500.0, None, None)
        assert s >= 15500.0 - 1e-6


# --- deadline pull ----------------------------------------------------------

def test_deadline_produces_larger_final_concession():
    # Compare the same round with vs. without a deadline one round away.
    cp = 17000.0
    normal = next_offer("buyer", 6, BUYER_RES, cp, None, None)
    deadline = next_offer("buyer", 6, BUYER_RES, cp, None, deadline_round=7)
    # With a deadline pull toward the midpoint, the buyer concedes at least as
    # much (moves up toward the seller) as it would without one.
    assert deadline >= normal - 1e-6


# --- tactic modulation ------------------------------------------------------

def test_walk_away_threat_makes_buyer_concede_more_than_neutral():
    r = 4
    neutral = next_offer("buyer", r, BUYER_RES, None, None, None)
    threatened = next_offer("buyer", r, BUYER_RES, None, "walk_away_threat", None)
    assert threatened >= neutral  # concede more == bid higher (toward budget)


def test_anchoring_makes_buyer_hold_firmer():
    r = 4
    neutral = next_offer("buyer", r, BUYER_RES, None, None, None)
    anchored = next_offer("buyer", r, BUYER_RES, None, "anchoring", None)
    assert anchored <= neutral  # hold firmer == bid lower


# --- zopa helper ------------------------------------------------------------

def test_has_zopa():
    assert has_zopa(20000, 15000) is True    # buyer max >= seller min
    assert has_zopa(14000, 15000) is False   # no overlap


# --- input validation -------------------------------------------------------

def test_invalid_side_raises():
    with assert_raises(ValueError):
        next_offer("landlord", 1, 100, None, None, None)


def test_invalid_round_raises():
    with assert_raises(ValueError):
        next_offer("buyer", 0, 100, None, None, None)
