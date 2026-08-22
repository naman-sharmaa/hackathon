"""
llm_client.py — the ONE place every model call goes through.

Responsibilities (spec 4.8):
  * OpenRouter primary call (OpenAI-compatible /chat/completions) over stdlib
    urllib — no third-party HTTP dependency.
  * Retry with exponential backoff (default 3 attempts).
  * Per-side circuit breaker: after N consecutive failures on a side, trip to
    the fallback for the rest of the session until a call succeeds again.
  * Graceful degradation ladder:  OpenRouter -> Ollama (local) -> deterministic
    mock narrator.  The deal math is unaffected at every rung — only the prose
    gets simpler.
  * Centralized call log so the eval harness / dashboard can report on it.

Because the mock narrator always embeds the engine's exact number, AI messages
pass validator price-consistency *by construction* (belt); the validator still
checks independently (suspenders).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from config import SETTINGS

logger = logging.getLogger("dealbench.llm")

# Centralized, in-memory record of every model call (for the dashboard/report).
CALL_LOG: list[dict] = []


class OpenRouterError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Circuit breaker (per side, per session)
# ---------------------------------------------------------------------------
class CircuitBreaker:
    def __init__(self, threshold: int | None = None):
        self.threshold = threshold if threshold is not None else SETTINGS.circuit_breaker_threshold
        self.consecutive_failures = 0
        self.tripped = False
        self.trip_count = 0  # how many times it has tripped this session

    def record_success(self) -> None:
        if self.tripped:
            logger.info("circuit breaker RESET after a successful call")
        self.consecutive_failures = 0
        self.tripped = False

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold and not self.tripped:
            self.tripped = True
            self.trip_count += 1
            logger.warning("circuit breaker TRIPPED after %d consecutive failures",
                           self.consecutive_failures)

    @property
    def is_open(self) -> bool:
        return self.tripped


# ---------------------------------------------------------------------------
# Raw transport
# ---------------------------------------------------------------------------
def _http_post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_json(url: str, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_api_error(body: str) -> str:
    """Pull a human string out of an OpenRouter error body, if present."""
    try:
        obj = json.loads(body)
    except Exception:
        return body.strip()[:160]
    err = obj.get("error") if isinstance(obj, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or err)[:160]
    if err:
        return str(err)[:160]
    return ""


def _openrouter_chat(model: str, messages: list[dict], max_tokens: int,
                     temperature: float, timeout: int) -> str:
    if not SETTINGS.openrouter_api_key:
        raise OpenRouterError("no OPENROUTER_API_KEY configured")
    headers = {
        "Authorization": f"Bearer {SETTINGS.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if SETTINGS.app_url:
        headers["HTTP-Referer"] = SETTINGS.app_url
    if SETTINGS.app_title:
        headers["X-Title"] = SETTINGS.app_title
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    url = f"{SETTINGS.openrouter_base_url}/chat/completions"
    try:
        obj = _http_post_json(url, payload, headers, timeout)
    except urllib.error.HTTPError as e:
        # 4xx/5xx from the API — the body usually explains why (bad model, etc.)
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # pragma: no cover
            pass
        detail = _extract_api_error(body) or f"HTTP {e.code} {e.reason}"
        raise OpenRouterError(detail) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", None) or e
        raise OpenRouterError(f"network unreachable: {reason}") from e
    if isinstance(obj, dict) and obj.get("error"):
        raise OpenRouterError(_extract_api_error(json.dumps(obj)) or "api error")
    try:
        return obj["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise OpenRouterError(f"malformed response: {str(obj)[:120]}") from e


def _ollama_chat(model: str, messages: list[dict], timeout: int) -> str:
    """Local Ollama fallback via its OpenAI-compatible chat endpoint."""
    url = f"{SETTINGS.ollama_host}/api/chat"
    payload = {"model": model, "messages": messages, "stream": False}
    obj = _http_post_json(url, payload, {"Content-Type": "application/json"}, timeout)
    # Ollama returns {"message": {"content": ...}}
    return obj["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Retry wrapper + stateless single-shot (used by the classifier)
# ---------------------------------------------------------------------------
def _log_call(backend: str, model: str, ok: bool, latency_ms: float, note: str = "") -> None:
    CALL_LOG.append({
        "ts": time.time(), "backend": backend, "model": model,
        "ok": ok, "latency_ms": round(latency_ms, 1), "note": note,
    })


def chat_once(model: str, messages: list[dict], max_tokens: int = 200,
              temperature: float = 0.6) -> str:
    """OpenRouter call with retry+backoff. Raises OpenRouterError if all
    attempts fail. Used where the caller wants to handle fallback itself
    (e.g. the tactic classifier)."""
    attempts = SETTINGS.max_retries
    last_err: Exception | None = None
    for i in range(attempts):
        t0 = time.time()
        try:
            out = _openrouter_chat(model, messages, max_tokens, temperature,
                                   SETTINGS.timeout_seconds)
            _log_call("openrouter", model, True, (time.time() - t0) * 1000)
            return out
        except OpenRouterError as e:
            last_err = e
            _log_call("openrouter", model, False, (time.time() - t0) * 1000, str(e))
            if i < attempts - 1:
                time.sleep(min(8.0, 0.5 * (2 ** i)))  # 0.5s, 1s, 2s, ...
    raise OpenRouterError(f"all {attempts} attempts failed: {last_err}")


# ---------------------------------------------------------------------------
# Live diagnostics — "is the real API actually working for buyer & seller?"
#
# This is the single source of truth behind both the CLI (`check_llm.py`) and
# the GET /health/llm endpoint the UI's LIVE/MOCK badge reads. probe_model does
# ONE tiny call and never raises, so a diagnostic can report per-model status
# (bad key -> 401, delisted model -> 404, no credit -> 402, etc.) instead of the
# session silently degrading to the mock narrator.
# ---------------------------------------------------------------------------
def probe_model(model: str, timeout: int | None = None) -> dict:
    """One minimal completion to verify a model is reachable and answering.

    Returns {"model", "ok", "latency_ms", "sample", "error"} — never raises."""
    t0 = time.time()
    messages = [{"role": "user", "content": "Reply with the single word: OK"}]
    try:
        out = _openrouter_chat(model, messages, max_tokens=5, temperature=0.0,
                               timeout=timeout or SETTINGS.timeout_seconds)
        return {"model": model, "ok": True,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "sample": out[:60], "error": ""}
    except OpenRouterError as e:
        return {"model": model, "ok": False,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "sample": "", "error": str(e)}


def list_models(timeout: int | None = None) -> dict:
    """List the models the gateway currently offers (OpenAI-compatible GET
    /models). Lets you confirm the exact IDs to put in .env instead of guessing
    — a wrong ID is the #1 cause of a silent fallback to the mock narrator.

    Returns {"ok", "ids": [...], "error"} and never raises. `ids` is sorted.
    Works with any OpenAI-style gateway (OpenRouter, OpenCode Zen, Together, …)
    since they all expose the same {"data":[{"id":...}]} shape (a bare list is
    also tolerated)."""
    if not SETTINGS.openrouter_api_key:
        return {"ok": False, "ids": [], "error": "no OPENROUTER_API_KEY configured"}
    headers = {
        "Authorization": f"Bearer {SETTINGS.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if SETTINGS.app_url:
        headers["HTTP-Referer"] = SETTINGS.app_url
    if SETTINGS.app_title:
        headers["X-Title"] = SETTINGS.app_title
    url = f"{SETTINGS.openrouter_base_url}/models"
    try:
        obj = _http_get_json(url, headers, timeout or SETTINGS.timeout_seconds)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # pragma: no cover
            pass
        detail = _extract_api_error(body) or f"HTTP {e.code} {e.reason}"
        return {"ok": False, "ids": [], "error": detail}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        reason = getattr(e, "reason", None) or e
        return {"ok": False, "ids": [], "error": f"could not reach {url}: {reason}"}

    # Accept {"data":[{"id":...}]} (OpenAI style) or a bare list of dicts/strings.
    rows = obj.get("data") if isinstance(obj, dict) else obj
    if not isinstance(rows, list):
        return {"ok": False, "ids": [], "error": f"unexpected /models shape: {str(obj)[:120]}"}
    ids = []
    for r in rows:
        if isinstance(r, str):
            ids.append(r)
        elif isinstance(r, dict):
            mid = r.get("id") or r.get("name") or r.get("model")
            if mid:
                ids.append(str(mid))
    return {"ok": True, "ids": sorted(set(ids)), "error": ""}


def diagnose(probe: bool = False) -> dict:
    """Report how narration will be produced right now.

    Without `probe`, this is a zero-cost config snapshot (key present? offline
    flag? which models?). With `probe=True`, it actually pings the buyer, seller
    and classifier models and returns a verdict:

      live    -> both buyer & seller models answered (chat will be real)
      partial -> only one side answered (that side is live, the other degrades)
      mock    -> neither answered (chat will use the offline narrator)
    """
    cfg = {
        "key_present": bool(SETTINGS.openrouter_api_key),
        "offline_flag": SETTINGS.offline,
        "base_url": SETTINGS.openrouter_base_url,
        "buyer_model": SETTINGS.buyer_model,
        "seller_model": SETTINGS.seller_model,
        "classifier_model": SETTINGS.classifier_model,
        "expected_mode": "live" if SETTINGS.has_openrouter else "offline",
    }
    out: dict = {"config": cfg, "probed": False}

    if not probe:
        if not cfg["key_present"]:
            out["reason"] = "No OPENROUTER_API_KEY set — chat will use the offline narrator."
        elif cfg["offline_flag"]:
            out["reason"] = "DEALBENCH_OFFLINE=1 — chat is forced to the offline narrator."
        else:
            out["reason"] = "Key present and online — run with probe=1 to confirm the models answer."
        return out

    out["probed"] = True
    if not SETTINGS.has_openrouter:
        out["verdict"] = "mock"
        out["reason"] = cfg_reason = (
            "No OPENROUTER_API_KEY set — nothing to probe."
            if not cfg["key_present"] else
            "DEALBENCH_OFFLINE=1 — API calls are disabled.")
        return out

    checks = {
        "buyer": probe_model(SETTINGS.buyer_model),
        "seller": probe_model(SETTINGS.seller_model),
        "classifier": probe_model(SETTINGS.classifier_model),
    }
    out["checks"] = checks
    buyer_ok, seller_ok = checks["buyer"]["ok"], checks["seller"]["ok"]
    if buyer_ok and seller_ok:
        out["verdict"] = "live"
        out["reason"] = "Both buyer and seller models answered — negotiations will use the real API."
    elif buyer_ok or seller_ok:
        out["verdict"] = "partial"
        bad = "seller" if buyer_ok else "buyer"
        out["reason"] = (f"The {bad} model failed ({checks[bad]['error']}). "
                         f"That side will fall back; fix its model ID in .env.")
    else:
        out["verdict"] = "mock"
        out["reason"] = (f"Both models failed (buyer: {checks['buyer']['error']}). "
                         f"Chat will use the offline narrator until the model IDs / key are fixed.")
    return out


# ---------------------------------------------------------------------------
# Deterministic mock narrator (offline / final fallback)
#
# Composed from opener + core (+ optional tactic flavor + phase clause), indexed
# by a seed derived from the round and the engine's number. It's deterministic
# (so tests are stable) but the combinatorics mean consecutive turns don't
# repeat the way a 5-line cycle did. The engine number is ALWAYS embedded, so
# price-consistency still holds by construction.
# ---------------------------------------------------------------------------
def _fmt(amount: float, currency: str) -> str:
    return f"{currency}{amount:,.0f}"


_OPENERS = {
    "buyer": [
        "Thanks for walking me through it.", "Okay, I've been thinking about this.",
        "I appreciate the detail on the place.", "Let's keep this moving.",
        "Fair enough on your end.", "I hear you.", "I've run my numbers.",
        "I want to make this work.", "Understood.", "Right, here's where I land.",
    ],
    "seller": [
        "Appreciate the offer.", "Thanks for staying at the table.",
        "I understand where you're coming from.", "Let me be straight with you.",
        "I've looked at what you're proposing.", "Noted.",
        "I want to find a deal here too.", "Here's the reality on my side.",
        "Okay.", "I'll be candid.",
    ],
}
_CORES = {
    "buyer": [
        "I can go to {price}.", "My offer is {price}.", "Let's call it {price}.",
        "I'm comfortable at {price}.", "I'll put {price} on the table.",
        "{price} is where I can be.", "I can stretch to {price}.",
        "How about {price}?", "I'd like to settle around {price}.",
        "That puts me at {price}.",
    ],
    "seller": [
        "I can come to {price}.", "The number I need is {price}.",
        "I'd want {price} for it.", "Let's say {price}.",
        "I can meet you at {price}.", "{price} is fair on my side.",
        "I'll do {price}.", "My ask is {price}.",
        "I can bring it to {price}.", "That works out to {price}.",
    ],
}
_TACTIC_FLAVOR = {
    "walk_away_threat": [
        " I do have other options, so I can't chase this forever.",
        " I'm prepared to walk if we can't get close.",
    ],
    "comparables": [
        " Comparable places nearby sit in a similar range.",
        " The comps in this area back that up.",
    ],
    "deadline_pressure": [
        " I'd like to wrap this up this week rather than drag it out.",
        " There's a clock on this for me, to be honest.",
    ],
    "anchoring": [
        " That's a considered number, not an opening throwaway.",
        " I've priced that deliberately.",
    ],
    "splitting_difference": [
        " I'm happy to meet closer to the middle.",
        " Let's try to split the gap sensibly.",
    ],
    "flattery": [
        " You've clearly looked after the place, and that matters to me.",
        " It's a genuinely nice property — I want this to work.",
    ],
}
_PHASE = {
    "early": ["", "", " Let's see where this goes."],
    "mid": ["", " I think we're not far off.", " We're getting closer."],
    "late": [" Let's try to close this out.", " I'd like to land this.",
             " We're close — let's finish it."],
}
_ACCEPT_LINES = [
    "That works for me — let's do {price}. I'll consider us agreed, subject to the usual paperwork.",
    "Deal. {price} it is — I'm glad we got there. We can move to paperwork.",
    "Yes, {price} works. Let's shake on it, subject to the standard documents.",
    "Happy to agree at {price}. Let's get the paperwork moving.",
]
_WALK_LINES = [
    "I don't think we can bridge the gap on this one. I'll step away — no hard feelings.",
    "We're too far apart for me to make this work. I'll have to pass, but thank you.",
    "This isn't coming together at a number that works. I'll bow out here.",
    "I don't see a deal here today. Appreciate your time all the same.",
]


def _phase_key(round_num: int) -> str:
    if round_num <= 2:
        return "early"
    if round_num <= 5:
        return "mid"
    return "late"


def _pick(pool: list, seed: int):
    return pool[seed % len(pool)] if pool else ""


def mock_narrate(side: str, engine_offer: float, tactic: str | None,
                 round_num: int, mode: str, currency: str = "$") -> str:
    price = _fmt(engine_offer, currency)
    seed = int(round(engine_offer)) + round_num * 31 + (0 if side == "buyer" else 17)
    if mode == "accept":
        return _pick(_ACCEPT_LINES, seed).format(price=price)
    if mode == "walk":
        return _pick(_WALK_LINES, seed)

    opener = _pick(_OPENERS[side], seed)
    core = _pick(_CORES[side], seed // 7).format(price=price)
    text = f"{opener} {core}"

    # Occasionally add a tactic flavor (when the counterparty used one).
    flavors = _TACTIC_FLAVOR.get(tactic or "", [])
    if flavors and seed % 3 == 0:
        text += _pick(flavors, seed // 11)
    else:
        # Otherwise a light phase clause, so length and rhythm vary turn to turn.
        text += _pick(_PHASE[_phase_key(round_num)], seed // 13)
    return text.strip()


def ensure_price_in_text(text: str, engine_offer: float | None, currency: str = "$") -> str:
    """Guarantee the engine's number is present so AI price-consistency holds
    even if a small model forgot to state it."""
    if engine_offer is None:
        return text
    from engine.validator import extract_prices
    prices = extract_prices(text)
    if any(abs(p - engine_offer) <= max(50.0, 0.02 * engine_offer) for p in prices):
        return text
    return f"{text.rstrip()} (To be precise, my number is {_fmt(engine_offer, currency)}.)"


# ---------------------------------------------------------------------------
# The client agents actually use
# ---------------------------------------------------------------------------
@dataclass
class NarrationResult:
    text: str
    backend: str          # 'openrouter' | 'ollama' | 'mock' | 'human'
    degraded: bool        # True if we didn't use the primary OpenRouter model
    circuit_open: bool = False
    reason: str = ""      # human-readable WHY (esp. when degraded)


@dataclass
class LLMClient:
    """Holds per-side circuit-breaker state for one session."""
    breakers: dict = field(default_factory=lambda: {
        "buyer": CircuitBreaker(), "seller": CircuitBreaker(),
    })
    # Last narration backend + why, per side — surfaced to the UI so a 'mock'
    # badge is never a mystery ("openrouter unreachable: 403", "no API key", …).
    last_reason: dict = field(default_factory=lambda: {"buyer": "", "seller": ""})

    def _why_mock(self, side: str, last_err: str, skip_primary: bool) -> str:
        if not SETTINGS.openrouter_api_key:
            return "no OPENROUTER_API_KEY set — using offline narrator"
        if SETTINGS.offline:
            return "DEALBENCH_OFFLINE=1 — using offline narrator"
        if self.breakers[side].is_open:
            return f"circuit breaker open after repeated failures ({last_err})".strip()
        if skip_primary:
            return "fallback narrator (primary skipped)"
        return last_err or "primary model unavailable"

    def narrate(self, side: str, system_prompt: str, context_messages: list[dict],
                engine_offer: float | None, tactic: str | None, round_num: int,
                mode: str = "offer", currency: str = "$",
                skip_primary: bool = False) -> NarrationResult:
        """Produce one narration turn for `side`, degrading gracefully.

        `skip_primary=True` bypasses OpenRouter entirely (used by
        FallbackAgent and the live 'kill the network' demo)."""
        breaker = self.breakers[side]
        instruction = self._offer_instruction(engine_offer, mode, currency)
        messages = [{"role": "system", "content": system_prompt}] + context_messages
        if instruction:
            messages.append({"role": "system", "content": instruction})
        # A touch more heat on offers => more varied phrasing; steadier on close.
        temperature = 0.85 if mode == "offer" else 0.5
        last_err = ""

        # Rung 1: OpenRouter, unless offline / skipped / the breaker is open.
        if SETTINGS.has_openrouter and not breaker.is_open and not skip_primary:
            try:
                text = chat_once(SETTINGS.model_for(side), messages,
                                 max_tokens=180, temperature=temperature)
                breaker.record_success()
                self.last_reason[side] = ""
                text = ensure_price_in_text(text, engine_offer, currency)
                return NarrationResult(text, "openrouter", degraded=False)
            except OpenRouterError as e:
                last_err = str(e)
                logger.warning("OpenRouter failed for %s: %s", side, e)
                breaker.record_failure()

        # Rung 2: local Ollama.
        if SETTINGS.has_openrouter or breaker.is_open or skip_primary:
            try:
                t0 = time.time()
                text = _ollama_chat(SETTINGS.ollama_model, messages, SETTINGS.timeout_seconds)
                _log_call("ollama", SETTINGS.ollama_model, True, (time.time() - t0) * 1000)
                breaker.record_success()
                self.last_reason[side] = f"OpenRouter unavailable ({last_err}); using local Ollama" if last_err else "using local Ollama"
                text = ensure_price_in_text(text, engine_offer, currency)
                return NarrationResult(text, "ollama", degraded=True,
                                       circuit_open=breaker.is_open,
                                       reason=self.last_reason[side])
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    OSError, KeyError, json.JSONDecodeError) as e:
                logger.info("Ollama fallback unavailable for %s: %s", side, e)
                _log_call("ollama", SETTINGS.ollama_model, False, 0.0, str(e))

        # Rung 3: deterministic mock narrator (always succeeds).
        text = mock_narrate(side, engine_offer or 0.0, tactic, round_num, mode, currency)
        _log_call("mock", "deterministic", True, 0.0)
        reason = self._why_mock(side, last_err, skip_primary)
        self.last_reason[side] = reason
        return NarrationResult(text, "mock", degraded=not SETTINGS.has_openrouter,
                               circuit_open=breaker.is_open, reason=reason)

    @staticmethod
    def _offer_instruction(engine_offer: float | None, mode: str, currency: str) -> str:
        if mode == "accept":
            return (f"Accept the deal warmly in ONE short line and state the agreed "
                    f"price {_fmt(engine_offer or 0, currency)} exactly. Subject to paperwork.")
        if mode == "walk":
            return ("Politely end the negotiation in ONE short line without revealing "
                    "any secret number. Do not state a price.")
        if engine_offer is None:
            return "Reply in ONE or two short, natural negotiation sentences."
        return (f"State your current offer, which is EXACTLY {_fmt(engine_offer, currency)}, "
                f"in ONE or two natural sentences. Use this number verbatim; never reveal "
                f"your own budget ceiling or floor. Vary your wording from previous turns — "
                f"do not reuse the same opener or sentence you used before; sound like a real "
                f"person mid-conversation, not a template.")
