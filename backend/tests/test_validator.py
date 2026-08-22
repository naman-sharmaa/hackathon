"""Tests for validator.py — price consistency + reservation-price leak, on
both agent and human messages, no source exemptions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.validator import validate_message, extract_prices


# --- price extraction across formats ----------------------------------------

def test_extract_plain_and_currency():
    assert 17400 in extract_prices("I can do $17,400 this month")
    assert 17400 in extract_prices("my offer is 17400")


def test_extract_k_and_grand_and_lakh():
    assert 17400 in extract_prices("how about 17.4k")
    assert 20000 in extract_prices("I have 20 grand ready")
    assert 200000 in extract_prices("the place is worth 2 lakh")


def test_extract_spelled_out():
    assert 20000 in extract_prices("my ceiling is twenty thousand rupees")
    assert 15000 in extract_prices("fifteen thousand is my floor")


# --- price consistency ------------------------------------------------------

def test_agent_quoting_engine_number_passes():
    r = validate_message("I'll offer $17,400 for the unit.", "buyer", 4,
                         engine_offer=17400, reservation_price=20000, source="agent")
    assert r.price_ok is True
    assert r.leak_detected is False


def test_wrong_number_fails_price_check():
    r = validate_message("Actually I'll only pay 16000.", "buyer", 4,
                         engine_offer=17400, reservation_price=20000, source="agent")
    assert r.price_ok is False


def test_no_number_is_price_ok():
    r = validate_message("Let me think about that and get back to you.", "buyer", 4,
                         engine_offer=17400, reservation_price=20000, source="agent")
    assert r.price_ok is True


def test_human_wrong_number_reported_not_exempt():
    # A human may type any number; validator still reports the mismatch (the
    # session layer decides override policy, not the validator).
    r = validate_message("no, my number is 16500", "buyer", 4,
                         engine_offer=17400, reservation_price=20000, source="human")
    assert r.price_ok is False  # reported, not silently exempted


# --- leak detection (both sources) ------------------------------------------

def test_leak_direct_number_agent():
    r = validate_message("Honestly the most I can pay is 20000.", "buyer", 3,
                         engine_offer=17000, reservation_price=20000, source="agent")
    assert r.leak_detected is True
    assert r.leaked_value == 20000


def test_leak_human_takeover_not_exempt():
    # The human "accidentally" leaks their own ceiling during a takeover.
    r = validate_message("between us, I could actually stretch to 20k", "buyer", 5,
                         engine_offer=18000, reservation_price=20000, source="human")
    assert r.leak_detected is True


def test_leak_spelled_out():
    r = validate_message("my budget is really twenty thousand", "buyer", 2,
                         engine_offer=15000, reservation_price=20000, source="agent")
    assert r.leak_detected is True


def test_clean_message_no_leak():
    r = validate_message("I can offer $17,400, that's a strong bid.", "buyer", 4,
                         engine_offer=17400, reservation_price=20000, source="agent")
    assert r.leak_detected is False


def test_quoting_own_current_offer_is_not_a_leak():
    # Quoting the engine offer (17400) must not be mistaken for the reservation.
    r = validate_message("My offer stands at 17,400.", "buyer", 4,
                         engine_offer=17400, reservation_price=20000, source="agent")
    assert r.price_ok is True
    assert r.leak_detected is False
