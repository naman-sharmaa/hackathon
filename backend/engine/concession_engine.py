"""
concession_engine.py — the deterministic heart of DealBench.

**No LLM ever touches this file.**  Given a side, a round number, that side's
reservation price, the counterparty's last offer, an optional detected tactic,
and an optional deadline, it returns the side's next numeric offer.  The LLM's
only job elsewhere is to narrate whatever number this function decides.

Design (closed-form, stateless, therefore trivially testable)
-------------------------------------------------------------
Each side concedes from an opening *anchor* toward its *reservation price*
along a geometric curve whose per-round step shrinks over time:

    conceded_fraction(r) = 1 - decay ** (r - 1)      # r = 1 -> 0 (anchor)

    buyer_offer(r)  = anchor_b + conceded * (reservation_b - anchor_b)   # rises
    seller_offer(r) = anchor_s - conceded * (anchor_s - reservation_s)   # falls

Because ``conceded < 1`` for every finite round, an offer can never *cross*
its own reservation price.  Two extra guards drive convergence and realism:

* **No crossover** — a buyer never bids above what the seller is currently
  asking, and a seller never asks below what the buyer is currently bidding.
* **Deadline pull** — within one round of ``deadline_round`` we blend toward
  the midpoint of (our curve offer, counterparty's offer): a bigger, final,
  "let's just close this" concession instead of another flat step.
* **Tactic modulation** — a walk-away threat or deadline pressure from the
  other side nudges our concession up a touch; heavy anchoring makes us hold
  a touch firmer.  Always bounded so reservation is still never crossed.
"""
from __future__ import annotations

from config import SETTINGS

_ENG = SETTINGS.engine

# How far each side opens from its reservation price when no explicit opening
# anchor is supplied by the caller (buyer opens *below* budget, seller opens
# *above* floor).  Reconstructing the anchor this way keeps `next_offer`
# stateless while still producing a believable opening stance.
DEFAULT_OPEN_GAP_FRACTION = 0.25

# Concession multipliers applied when the *counterparty's* last message carried
# a given tactic.  >1 means "concede a bit more"; <1 means "hold firmer".
_TACTIC_CONCESSION_MULTIPLIER = {
    "walk_away_threat": 1.20,
    "deadline_pressure": 1.15,
    "comparables": 1.10,
    "splitting_difference": 1.10,
    "anchoring": 0.90,
    "silence": 0.95,
}


def opening_offer(side: str, reservation_price: float,
                  open_gap_fraction: float = DEFAULT_OPEN_GAP_FRACTION) -> float:
    """The round-1 anchor for a side when none is supplied explicitly."""
    if side == "buyer":
        # Budget ceiling is the reservation; open below it.
        return round(reservation_price * (1.0 - open_gap_fraction), 2)
    # Seller: floor is the reservation; open above it.
    return round(reservation_price * (1.0 + open_gap_fraction), 2)


def _conceded_fraction(round_num: int, decay: float) -> float:
    """Cumulative fraction of the anchor->reservation distance conceded by
    ``round_num``.  Round 1 -> 0.0 (still at anchor); grows toward (never
    reaching) 1.0 with diminishing per-round increments."""
    exponent = max(0, round_num - 1)
    return 1.0 - (decay ** exponent)


def next_offer(side: str, round_num: int, reservation_price: float,
               counterparty_last_offer: float | None, tactic: str | None,
               deadline_round: int | None,
               *,
               opening_anchor: float | None = None,
               decay: float | None = None) -> float:
    """Deterministic concession curve.

    Parameters
    ----------
    side : "buyer" | "seller"
    round_num : 1-based negotiation round for this side's offer.
    reservation_price : this side's walk-away number (buyer: max budget;
        seller: min acceptable).  The returned offer never crosses it.
    counterparty_last_offer : the other side's most recent number, or None on
        the opening round.  Used for the no-crossover guard and deadline pull.
    tactic : the counterparty's detected tactic (optional) — modulates the
        concession size, never the reservation bound.
    deadline_round : if set and we're within 1 round of it, apply a larger
        final concession toward the midpoint instead of a flat step.
    opening_anchor : explicit round-1 stance (from constraints intake). If
        None, derived from ``reservation_price``.
    decay : override the global concession decay (mostly for tests).

    Returns
    -------
    float : the side's offer for this round, rounded to cents.
    """
    if side not in ("buyer", "seller"):
        raise ValueError(f"side must be 'buyer' or 'seller', got {side!r}")
    if round_num < 1:
        raise ValueError("round_num is 1-based and must be >= 1")

    decay = _ENG.concession_decay if decay is None else decay
    anchor = opening_offer(side, reservation_price) if opening_anchor is None else opening_anchor

    # Base cumulative concession for this round.
    conceded = _conceded_fraction(round_num, decay)

    # Tactic modulation — bounded to [0, 0.98] so we never reach reservation.
    if tactic:
        mult = _TACTIC_CONCESSION_MULTIPLIER.get(tactic, 1.0)
        conceded = min(0.98, max(0.0, conceded * mult))

    # Curve offer (before crossover / deadline handling).
    span = reservation_price - anchor  # buyer: positive (rises); seller: negative (falls)
    offer = anchor + conceded * span

    # Enforce the reservation bound explicitly (belt-and-suspenders vs. rounding).
    if side == "buyer":
        offer = min(offer, reservation_price)      # never pay above budget
    else:
        offer = max(offer, reservation_price)      # never sell below floor

    # Deadline pull: a bigger, final concession toward a deal.
    at_deadline = deadline_round is not None and round_num >= (deadline_round - 1)
    if at_deadline and counterparty_last_offer is not None:
        midpoint = (offer + counterparty_last_offer) / 2.0
        offer = offer + (midpoint - offer) * _ENG.deadline_midpoint_pull
        # Re-apply reservation bound after the pull.
        offer = min(offer, reservation_price) if side == "buyer" else max(offer, reservation_price)

    # No-crossover guard: don't bid above the ask / ask below the bid.
    if counterparty_last_offer is not None:
        if side == "buyer":
            offer = min(offer, counterparty_last_offer)
        else:
            offer = max(offer, counterparty_last_offer)

    return round(offer, 2)


def has_zopa(buyer_reservation: float, seller_reservation: float) -> bool:
    """True when a Zone Of Possible Agreement exists: the buyer's ceiling is at
    or above the seller's floor.  Used by the grader and for scenario sanity."""
    return buyer_reservation >= seller_reservation
