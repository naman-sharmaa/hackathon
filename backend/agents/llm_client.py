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
    try:
        obj = _http_post_json(f"{SETTINGS.openrouter_base_url}/chat/completions",
                              payload, headers, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        raise OpenRouterError(f"transport error: {e}") from e
    try:
        return obj["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise OpenRouterError(f"malformed response: {obj}") from e


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
# Deterministic mock narrator (offline / final fallback)
# ---------------------------------------------------------------------------
def _fmt(amount: float, currency: str) -> str:
    return f"{currency}{amount:,.0f}"


_OFFER_LINES = {
    "buyer": [
        "Thanks for the details. I'd like to open at {price}.",
        "I've looked at the numbers — I can offer {price}.",
        "Let's keep this moving. My bid is {price}.",
        "I hear you, but {price} is where I am right now.",
        "Alright, I'll come up to {price}.",
    ],
    "seller": [
        "Appreciated. To start, the price I'm looking at is {price}.",
        "Given the demand, I'd want {price} for it.",
        "I can come down a little — say {price}.",
        "That's a bit low for me. I'm at {price}.",
        "Okay, I'll meet you partway at {price}.",
    ],
}
_TACTIC_FLAVOR = {
    "walk_away_threat": " I do have other options, so I won't stretch forever.",
    "comparables": " Comparable places in the area are in a similar range, for what it's worth.",
    "deadline_pressure": " I'd like to wrap this up soon rather than drag it out.",
    "anchoring": " That's a considered number, not an opening throwaway.",
    "splitting_difference": " I'm happy to find a middle ground here.",
}


def mock_narrate(side: str, engine_offer: float, tactic: str | None,
                 round_num: int, mode: str, currency: str = "$") -> str:
    price = _fmt(engine_offer, currency)
    if mode == "accept":
        return (f"That works for me — let's do {price}. "
                "I'll consider us agreed, subject to the usual paperwork.")
    if mode == "walk":
        return ("I don't think we can bridge the gap on this one. "
                "I'll have to step away — no hard feelings.")
    lines = _OFFER_LINES[side]
    base = lines[(round_num - 1) % len(lines)].format(price=price)
    flavor = _TACTIC_FLAVOR.get(tactic or "", "")
    return base + flavor


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
    backend: str          # 'openrouter' | 'ollama' | 'mock'
    degraded: bool        # True if we didn't use the primary OpenRouter model
    circuit_open: bool = False


@dataclass
class LLMClient:
    """Holds per-side circuit-breaker state for one session."""
    breakers: dict = field(default_factory=lambda: {
        "buyer": CircuitBreaker(), "seller": CircuitBreaker(),
    })

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

        # Rung 1: OpenRouter, unless offline / skipped / the breaker is open.
        if SETTINGS.has_openrouter and not breaker.is_open and not skip_primary:
            try:
                text = chat_once(SETTINGS.model_for(side), messages, max_tokens=180)
                breaker.record_success()
                text = ensure_price_in_text(text, engine_offer, currency)
                return NarrationResult(text, "openrouter", degraded=False)
            except OpenRouterError as e:
                logger.warning("OpenRouter failed for %s: %s", side, e)
                breaker.record_failure()

        # Rung 2: local Ollama.
        if SETTINGS.has_openrouter or breaker.is_open or skip_primary:
            try:
                t0 = time.time()
                text = _ollama_chat(SETTINGS.ollama_model, messages, SETTINGS.timeout_seconds)
                _log_call("ollama", SETTINGS.ollama_model, True, (time.time() - t0) * 1000)
                breaker.record_success()
                text = ensure_price_in_text(text, engine_offer, currency)
                return NarrationResult(text, "ollama", degraded=True,
                                       circuit_open=breaker.is_open)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    OSError, KeyError, json.JSONDecodeError) as e:
                logger.info("Ollama fallback unavailable for %s: %s", side, e)
                _log_call("ollama", SETTINGS.ollama_model, False, 0.0, str(e))

        # Rung 3: deterministic mock narrator (always succeeds).
        text = mock_narrate(side, engine_offer or 0.0, tactic, round_num, mode, currency)
        _log_call("mock", "deterministic", True, 0.0)
        return NarrationResult(text, "mock", degraded=not SETTINGS.has_openrouter,
                               circuit_open=breaker.is_open)

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
                f"your own budget ceiling or floor.")
