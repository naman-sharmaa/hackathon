"""
stopping_rules.py — deterministic negotiation termination.

Checked every round, no LLM involved.  Priority order matters and is chosen so
the outcome is never ambiguous:

  1. agreement  — offers have met (or crossed) or are within tolerance.
  2. walk_away  — a stated deadline round passed with no deal, OR the gap is
                  still too wide after a patience window.
  3. max_rounds — hard cap so the loop can never run forever, whatever else
                  is true.
  4. continue   — otherwise, negotiate on.
"""
from __future__ import annotations

from config import SETTINGS

_ENG = SETTINGS.engine

# The four possible outcomes, exported for callers/tests to reference safely.
CONTINUE = "continue"
AGREEMENT = "agreement"
WALK_AWAY = "walk_away"
MAX_ROUNDS = "max_rounds"


def check_stopping(buyer_offer: float, seller_offer: float, round_num: int,
                   tolerance: float | None = None,
                   max_rounds: int | None = None,
                   deadline_round: int | None = None) -> str:
    """Return one of: 'continue', 'agreement', 'walk_away', 'max_rounds'.

    Parameters
    ----------
    buyer_offer  : the buyer's current bid (lower side).
    seller_offer : the seller's current ask (higher side).
    round_num    : the round just completed (1-based).
    tolerance    : |buyer - seller| <= tolerance counts as a deal.
    max_rounds   : hard cap; reaching it with no deal ends the session.
    deadline_round : optional hard deadline; passing it with no deal walks away.
    """
    tolerance = _ENG.tolerance if tolerance is None else tolerance
    max_rounds = _ENG.max_rounds if max_rounds is None else max_rounds

    gap = abs(buyer_offer - seller_offer)

    # 1. Agreement — offers crossed (buyer willing to pay >= ask) or within tol.
    if buyer_offer >= seller_offer or gap <= tolerance:
        return AGREEMENT

    # 2a. Deadline passed with no agreement -> walk away, regardless of gap.
    if deadline_round is not None and round_num >= deadline_round:
        return WALK_AWAY

    # 3. Hard cap. Checked before the soft gap rule so it always wins ties.
    if round_num >= max_rounds:
        return MAX_ROUNDS

    # 2b. Soft walk-away: gap still too wide after the patience window.
    midpoint = (buyer_offer + seller_offer) / 2.0
    if (round_num >= _ENG.walk_away_patience
            and midpoint > 0
            and gap > _ENG.walk_away_gap_ratio * midpoint):
        return WALK_AWAY

    return CONTINUE


def is_terminal(status: str) -> bool:
    """True for any outcome that ends the negotiation."""
    return status in (AGREEMENT, WALK_AWAY, MAX_ROUNDS)
