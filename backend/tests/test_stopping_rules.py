"""Unit tests for the deterministic stopping rules. No LLM, no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.stopping_rules import (
    check_stopping, AGREEMENT, WALK_AWAY, MAX_ROUNDS, CONTINUE, is_terminal,
)


def test_agreement_within_tolerance():
    assert check_stopping(17800, 18000, 5, tolerance=500, max_rounds=20) == AGREEMENT


def test_agreement_on_crossover():
    # Buyer willing to pay more than the ask -> deal, even outside tolerance.
    assert check_stopping(18500, 18000, 5, tolerance=100, max_rounds=20) == AGREEMENT


def test_continue_when_gap_moderate_early():
    # Round 2, gap 2000 on ~17k midpoint (~12%) -> keep going.
    assert check_stopping(16000, 18000, 2, tolerance=500, max_rounds=20) == CONTINUE


def test_deadline_passed_no_deal_walks_away():
    assert check_stopping(14000, 18000, 7, tolerance=500, max_rounds=20,
                          deadline_round=7) == WALK_AWAY


def test_deadline_does_not_override_a_reached_agreement():
    # If they actually met on the deadline round, that's a deal, not a walk.
    assert check_stopping(17900, 18000, 7, tolerance=500, max_rounds=20,
                          deadline_round=7) == AGREEMENT


def test_max_rounds_cutoff():
    assert check_stopping(12000, 18000, 20, tolerance=500, max_rounds=20) == MAX_ROUNDS


def test_soft_walk_away_wide_gap_after_patience():
    # Round 8 (past patience 6), gap 8000 on ~14k midpoint (~57%) -> walk.
    assert check_stopping(10000, 18000, 8, tolerance=500, max_rounds=20) == WALK_AWAY


def test_is_terminal():
    assert is_terminal(AGREEMENT)
    assert is_terminal(WALK_AWAY)
    assert is_terminal(MAX_ROUNDS)
    assert not is_terminal(CONTINUE)
