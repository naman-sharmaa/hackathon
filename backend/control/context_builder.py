"""
context_builder.py — assembles the per-side chat history for an OpenRouter call
so an agent can resume mid-negotiation, even right after a human takeover.

The whole trick (spec 4.6):

  * Role mapping is BY SIDE, not by author. When building the Buyer's message
    list, every past Buyer message — whether typed by a human or written by
    buyer_agent — is role "assistant"; every Seller message is role "user".
    The model literally cannot tell a human wrote turn 4, and we don't tell it.

  * The system prompt (built by base_agent) asserts plain continuity and never
    mentions the handoff.

Because concession_engine.py already owns the canonical offer regardless of who
typed last, the resuming agent only has to narrate the next number — it doesn't
need to reconcile anything the human said. Consistency is free.
"""
from __future__ import annotations

from typing import Iterable


def build_context(history: Iterable, for_side: str) -> list[dict]:
    """history: iterable of objects/dicts with `.side` and `.content`."""
    out: list[dict] = []
    for m in history:
        side = m.side if hasattr(m, "side") else m["side"]
        content = m.content if hasattr(m, "content") else m["content"]
        out.append({
            "role": "assistant" if side == for_side else "user",
            "content": content,
        })
    return out
