"""
optimal_calc.py — deterministic post-hoc deal analysis (no LLM).

Given both reservation prices and the realized outcome, compute the ZOPA and
how each side did relative to the best they could plausibly have achieved.

Framing:
  ZOPA (zone of possible agreement) = [seller_reservation, buyer_reservation]
  when buyer_reservation >= seller_reservation, else empty.

  For a final price P inside the ZOPA:
    buyer_surplus  = buyer_reservation - P   (paid under the ceiling)
    seller_surplus = P - seller_reservation  (got above the floor)

  "Money left on the table" for a side = surplus the OTHER side captured, i.e.
  how much further this side could in principle have pushed the price:
    buyer_left_on_table  = P - seller_reservation
    seller_left_on_table = buyer_reservation - P

  If no deal was reached but a ZOPA existed, BOTH sides left the entire ZOPA
  (buyer_reservation - seller_reservation) on the table — a worse outcome than
  any in-ZOPA price.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class DealAnalysis:
    zopa_exists: bool
    zopa_low: float
    zopa_high: float
    zopa_size: float
    deal_reached: bool
    final_price: float | None
    fair_midpoint: float
    buyer_surplus: float | None
    seller_surplus: float | None
    buyer_left_on_table: float | None
    seller_left_on_table: float | None
    buyer_capture_pct: float | None   # share of ZOPA the buyer captured
    seller_capture_pct: float | None
    notes: str

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(buyer_reservation: float, seller_reservation: float,
            final_price: float | None, deal_reached: bool) -> DealAnalysis:
    zopa_exists = buyer_reservation >= seller_reservation
    low, high = seller_reservation, buyer_reservation
    size = max(0.0, high - low)
    midpoint = round((low + high) / 2.0, 2)

    if deal_reached and final_price is not None:
        buyer_surplus = round(buyer_reservation - final_price, 2)
        seller_surplus = round(final_price - seller_reservation, 2)
        buyer_left = round(final_price - seller_reservation, 2)
        seller_left = round(buyer_reservation - final_price, 2)
        buyer_pct = round(100 * buyer_surplus / size, 1) if size > 0 else None
        seller_pct = round(100 * seller_surplus / size, 1) if size > 0 else None
        notes = "Deal reached inside the ZOPA; surplus split as shown."
    else:
        buyer_surplus = seller_surplus = 0.0
        # No deal: everyone forfeited the whole potential surplus.
        buyer_left = seller_left = round(size, 2) if zopa_exists else 0.0
        buyer_pct = seller_pct = 0.0
        notes = ("No deal despite a ZOPA — both sides left the entire "
                 f"{size:.0f} surplus unclaimed." if zopa_exists
                 else "No overlap between buyer ceiling and seller floor; no deal was possible.")

    return DealAnalysis(
        zopa_exists=zopa_exists, zopa_low=low, zopa_high=high, zopa_size=round(size, 2),
        deal_reached=deal_reached, final_price=final_price, fair_midpoint=midpoint,
        buyer_surplus=buyer_surplus, seller_surplus=seller_surplus,
        buyer_left_on_table=buyer_left, seller_left_on_table=seller_left,
        buyer_capture_pct=buyer_pct, seller_capture_pct=seller_pct, notes=notes,
    )
