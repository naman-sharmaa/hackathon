#!/usr/bin/env python3
"""
check_llm.py — "is the real LLM gateway working for buyer AND seller?"

Run this on the machine that will host DealBench (where the network is open):

    python3 backend/check_llm.py                # probe buyer/seller/classifier
    python3 backend/check_llm.py --list-models   # list the gateway's model IDs

It reads backend/.env exactly the way the server does (now with zero install —
config.py parses .env itself if python-dotenv isn't present), then pings the
buyer, seller and classifier models with one tiny request each and tells you,
per model, whether it answered — and if not, the real reason (bad key, unknown
model id, out of credit, network). This is the fast way to know whether a
negotiation will stream REAL chat or silently fall back to the offline narrator.

Works with any OpenAI-compatible gateway (OpenRouter, OpenCode Zen, Together…);
the endpoint is whatever OPENROUTER_BASE_URL points at in .env.

Exit code: 0 if both buyer and seller answered (chat will be live), else 1.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the backend package importable no matter where we're launched from.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import SETTINGS  # noqa: E402
from agents.llm_client import diagnose, list_models  # noqa: E402


# --- tiny ANSI helpers (auto-disable when not a TTY) ------------------------
_C = sys.stdout.isatty()
def _g(s): return f"\033[32m{s}\033[0m" if _C else s   # green
def _r(s): return f"\033[31m{s}\033[0m" if _C else s   # red
def _y(s): return f"\033[33m{s}\033[0m" if _C else s   # yellow
def _b(s): return f"\033[1m{s}\033[0m" if _C else s    # bold
def _dim(s): return f"\033[2m{s}\033[0m" if _C else s  # dim


def _mask(key: str) -> str:
    if not key:
        return "(none)"
    return key[:8] + "…" + key[-4:] if len(key) > 14 else "set"


def _print_header() -> None:
    print(_b("\nDealBench · LLM gateway connectivity check"))
    print(_dim("─" * 52))
    print(f"  key            {_mask(SETTINGS.openrouter_api_key)}")
    print(f"  offline flag   {SETTINGS.offline}")
    print(f"  base url       {SETTINGS.openrouter_base_url}")
    print(f"  buyer model    {SETTINGS.buyer_model}")
    print(f"  seller model   {SETTINGS.seller_model}")
    print(f"  classifier     {SETTINGS.classifier_model}")
    print(_dim("─" * 52))


def _no_key_or_offline() -> int | None:
    """Shared preflight for the two commands. Returns an exit code to stop on,
    or None to continue."""
    if not SETTINGS.openrouter_api_key:
        print(_y("  No API key loaded from backend/.env."))
        print("  Put your gateway key in OPENROUTER_API_KEY in backend/.env")
        print(f"  (current base url: {SETTINGS.openrouter_base_url}), or leave it")
        print("  blank on purpose to use the offline narrator.")
        print(_dim("  Tip: config.py now reads .env with no pip install — if the key"))
        print(_dim("  still shows (none), check the line is 'OPENROUTER_API_KEY=sk-…'."))
        print()
        return 1
    if SETTINGS.offline:
        print(_y("  DEALBENCH_OFFLINE=1 — API calls are disabled by config."))
        print("  Set DEALBENCH_OFFLINE=0 in backend/.env to use the real API.\n")
        return 1
    return None


def cmd_list_models() -> int:
    """List the model IDs the configured gateway currently offers."""
    _print_header()
    stop = _no_key_or_offline()
    if stop is not None:
        return stop

    print(_dim("  fetching the gateway's model catalog…\n"))
    res = list_models()
    if not res["ok"]:
        print(_r("  Could not list models."))
        print("      " + _r(res.get("error", "") or "unknown error"))
        print(_dim("\n  If the gateway has no /models endpoint, this is expected —"))
        print(_dim("  just run the probe (no flag) to test your configured IDs directly."))
        print()
        return 1

    ids = res["ids"]
    print(_g(f"  {len(ids)} models available:"))
    for mid in ids:
        print("    " + mid)

    # Cross-check the three IDs the negotiation will actually use.
    print(_dim("\n" + "─" * 52))
    print(_b("  Your configured models:"))
    _crosscheck(ids)
    print()
    return 0


def _crosscheck(catalog_ids: list[str]) -> None:
    catalog = set(catalog_ids)
    any_bad = False
    for role, mid in (("buyer", SETTINGS.buyer_model),
                      ("seller", SETTINGS.seller_model),
                      ("classifier", SETTINGS.classifier_model)):
        if mid in catalog:
            print("  {} {:<11}{}".format(_g("✓"), role, _dim(mid)))
        else:
            any_bad = True
            print("  {} {:<11}{}  {}".format(_r("✗"), role, mid, _r("NOT in catalog")))
    if any_bad:
        print(_dim("  A model not in the catalog will fail and that side falls back to"))
        print(_dim("  the mock. Copy an exact ID from the list above into backend/.env."))


def main(argv: list[str]) -> int:
    if any(a in ("--list-models", "--models", "-l") for a in argv):
        return cmd_list_models()

    _print_header()
    stop = _no_key_or_offline()
    if stop is not None:
        return stop

    print(_dim("  probing models (one tiny request each)…\n"))
    result = diagnose(probe=True)
    checks = result.get("checks", {})

    for role in ("buyer", "seller", "classifier"):
        c = checks.get(role, {})
        if c.get("ok"):
            meta = "({:.0f} ms · {})".format(c.get("latency_ms", 0), c.get("model", ""))
            print("  {} {:<11}{} {}".format(_g("✓"), role, _g("answered"), _dim(meta)))
        else:
            print("  {} {:<11}{}  {}".format(_r("✗"), role, _r("FAILED"), _dim(c.get("model", ""))))
            print("      " + _r(c.get("error", "") or "unknown error"))

    verdict = result.get("verdict")
    print(_dim("\n" + "─" * 52))
    if verdict == "live":
        print(_g(_b("  LIVE ✓  Negotiations will stream real chat from the API.")))
    elif verdict == "partial":
        print(_y(_b("  PARTIAL  One side works; the other will fall back.")))
        print("  " + result.get("reason", ""))
    else:
        print(_r(_b("  MOCK ✗  Chat will use the offline narrator.")))
        print("  " + result.get("reason", ""))

    # When something failed, the usual culprit is a wrong model ID. Pull the
    # gateway's catalog (best-effort) and show exactly which IDs don't exist.
    if verdict != "live":
        cat = list_models()
        if cat["ok"]:
            print(_dim("\n  Cross-checking your model IDs against the gateway catalog:"))
            _crosscheck(cat["ids"])
            print(_dim(f"\n  Full list: python3 {Path(__file__).name} --list-models"))
        else:
            print(_dim("\n  (Could not fetch the model catalog to cross-check IDs: "
                       + (cat.get('error', '') or 'unknown') + ")"))
    print()
    return 0 if verdict == "live" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
