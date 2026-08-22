"""
validator.py — runs on EVERY message, agent or human, no exemptions.

Two independent checks (spec 4.4 + guardrails 1 & 5):

1. Price consistency — the price quoted in the text matches the number the
   deterministic engine computed for this round (within a small tolerance).
   AI messages should always pass because the agent is told to state the
   engine's number verbatim.  A human typing a *different* number is allowed
   (they're human) — it's reported, not blocked; session_state decides how to
   treat it (documented human-override choice in failure_log.md).

2. Reservation-price leak — the side's secret walk-away number (buyer budget
   ceiling / seller floor) must never appear, in digits, k/grand/lakh
   shorthand, spelled-out words, or next to a give-away phrase.  Applied to
   human-authored messages too, so a human "accidentally" leaking during a
   takeover is caught the same way an agent leak would be.

Nothing is silently dropped: every result carries human-readable `details`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    price_ok: bool
    leak_detected: bool
    details: str
    extracted_prices: list[float] = field(default_factory=list)
    matched_engine_price: float | None = None
    leaked_value: float | None = None

    def to_row(self) -> dict:
        """Flat dict for the messages table / API JSON."""
        return {
            "validator_price_ok": self.price_ok,
            "validator_leak_detected": self.leak_detected,
            "validator_details": self.details,
        }


# --- number parsing ---------------------------------------------------------

# Word -> value for spelled-out amounts (handles "twenty thousand", "fifteen k").
_WORD_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_WORD_SCALES = {
    "hundred": 100, "thousand": 1000, "grand": 1000, "k": 1000,
    "lakh": 100000, "lac": 100000, "million": 1_000_000, "crore": 10_000_000,
}
# Multiplier suffixes attached to digits: "17k", "1.5m", "2 lakh".
_SUFFIX_MULT = {
    "k": 1_000, "m": 1_000_000, "grand": 1_000,
    "lakh": 100_000, "lac": 100_000, "crore": 10_000_000, "thousand": 1_000,
    "hundred": 100, "mn": 1_000_000, "million": 1_000_000,
}

_NUM_RE = re.compile(
    r"""
    (?<![\w.])                       # not mid-word / mid-number
    (?:[$₹]|rs\.?|inr\s*)?            # optional currency marker
    \s*
    (\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)  # 1,234,567 or 17400 or 17.4
    \s*
    (k|m|mn|grand|thousand|hundred|lakh|lac|crore|million)?   # optional scale
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SPELLED_RE = re.compile(
    r"\b((?:(?:" + "|".join(_WORD_UNITS) + r")[\s-]*){1,3}"
    r"(?:" + "|".join(_WORD_SCALES) + r"))\b",
    re.IGNORECASE,
)


def _spelled_to_number(phrase: str) -> float | None:
    tokens = re.split(r"[\s-]+", phrase.lower().strip())
    total = 0.0
    current = 0.0
    seen = False
    for tok in tokens:
        if tok in _WORD_UNITS:
            current += _WORD_UNITS[tok]
            seen = True
        elif tok in _WORD_SCALES:
            current = (current or 1) * _WORD_SCALES[tok]
            total += current
            current = 0.0
            seen = True
    total += current
    return total if seen and total > 0 else None


def extract_prices(text: str) -> list[float]:
    """Pull every plausible monetary amount out of free text."""
    out: list[float] = []
    for m in _NUM_RE.finditer(text):
        raw, suffix = m.group(1), m.group(2)
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        if suffix:
            val *= _SUFFIX_MULT.get(suffix.lower(), 1)
        out.append(val)
    for m in _SPELLED_RE.finditer(text):
        val = _spelled_to_number(m.group(1))
        if val is not None:
            out.append(val)
    return out


# --- leak phrase signals ----------------------------------------------------

_LEAK_PHRASES = re.compile(
    r"\b(my (?:true |real |actual |absolute )?(?:max|maximum|budget|ceiling|"
    r"floor|limit|bottom line|reservation|walk[- ]?away)|"
    r"the most i(?:'?ll| will| can)|the (?:least|lowest) i(?:'?ll| will| can)|"
    r"i can'?t (?:go (?:above|below|over|under)|pay more than|accept less than)|"
    r"between (?:you and me|us)|honestly[, ]|to be honest|secretly|"
    r"don'?t tell|my secret number)\b",
    re.IGNORECASE,
)


def _near(a: float, b: float, rel: float, floor_abs: float) -> bool:
    return abs(a - b) <= max(floor_abs, rel * abs(b))


def validate_message(message: str, side: str, round_num: int,
                     engine_offer: float | None, reservation_price: float,
                     source: str,
                     price_tolerance: float | None = None) -> ValidationResult:
    """Validate one message. `source` is 'agent' or 'human' — NO source-based
    exemptions; both are checked identically (spec 4.4)."""
    prices = extract_prices(message)

    # --- Check 1: price consistency ---------------------------------------
    if engine_offer is None:
        price_ok, matched, price_note = True, None, "no engine offer to check against"
    elif not prices:
        # No number quoted (e.g. "let me think") — nothing can contradict.
        price_ok, matched, price_note = True, None, "no price quoted"
    else:
        tol = price_tolerance if price_tolerance is not None else max(50.0, 0.02 * engine_offer)
        matches = [p for p in prices if abs(p - engine_offer) <= tol]
        if matches:
            price_ok = True
            matched = min(matches, key=lambda p: abs(p - engine_offer))
            price_note = f"quoted {matched:.0f} matches engine {engine_offer:.0f}"
        else:
            price_ok = False
            matched = None
            closest = min(prices, key=lambda p: abs(p - engine_offer))
            price_note = (f"quoted {closest:.0f} != engine {engine_offer:.0f} "
                          f"(source={source})")

    # --- Check 2: reservation-price leak ----------------------------------
    leaked_value = None
    for p in prices:
        # A number within 2% (or exact) of the secret reservation is a leak.
        if _near(p, reservation_price, rel=0.02, floor_abs=1.0):
            leaked_value = p
            break
    phrase_hit = bool(_LEAK_PHRASES.search(message))
    # A give-away phrase sitting next to a looser-but-close number also leaks.
    if leaked_value is None and phrase_hit:
        for p in prices:
            if _near(p, reservation_price, rel=0.06, floor_abs=1.0):
                leaked_value = p
                break

    leak_detected = leaked_value is not None
    if leak_detected:
        leak_note = (f"LEAK: message reveals reservation ~{leaked_value:.0f} "
                     f"(secret {reservation_price:.0f}, side={side}, source={source})")
    elif phrase_hit:
        leak_note = "reveal-style phrasing present but no reservation-adjacent number"
    else:
        leak_note = "no leak"

    details = f"{price_note}; {leak_note}"
    return ValidationResult(
        price_ok=price_ok,
        leak_detected=leak_detected,
        details=details,
        extracted_prices=prices,
        matched_engine_price=matched,
        leaked_value=leaked_value,
    )
