"""
routes/health.py — LLM connectivity diagnostics for the LIVE/MOCK badge.

  GET /health/llm            -> zero-cost config snapshot (does the key/flag say
                                we'll use the real API, or the offline narrator?)
  GET /health/llm?probe=1    -> actually pings the buyer, seller & classifier
                                models and returns a verdict (live/partial/mock)
                                with the real per-model error if one fails.

The probe makes real API calls, so the UI only triggers it on demand ("Test
connection"), never on every render.
"""
from __future__ import annotations

from agents.llm_client import diagnose


def llm_health(params, body, query):
    probe = str(query.get("probe", "")).lower() in {"1", "true", "yes", "on"}
    return 200, diagnose(probe=probe)
