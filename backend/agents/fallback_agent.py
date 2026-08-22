"""
fallback_agent.py — same call interface as Buyer/Seller, but never touches
OpenRouter. It narrates via local Ollama, falling through to the deterministic
mock narrator (spec 4.7).

Two uses:
  * The circuit breaker in llm_client already degrades automatically; but
    session_state can also *explicitly swap* a side to a FallbackAgent when its
    breaker trips, so the degraded state is visible and demoable.
  * The live "kill the network" bit: force this agent to prove the deal keeps
    running with correct numbers while the prose simplifies.

Crucially, `concession_engine.py` output is unchanged — only narration degrades.
"""
from __future__ import annotations

from agents.base_agent import BaseAgent
from agents.llm_client import LLMClient, NarrationResult


class FallbackAgent(BaseAgent):
    def __init__(self, side: str, client: LLMClient, currency: str = "$"):
        super().__init__(side, client, currency=currency)

    def respond(self, context_messages: list[dict], engine_offer: float | None,
                tactic: str | None, round_num: int, mode: str = "offer",
                *, skip_primary: bool = True) -> NarrationResult:
        # skip_primary defaults True here: this agent, by definition, does not
        # use the primary OpenRouter model.
        return super().respond(context_messages, engine_offer, tactic, round_num,
                                mode, skip_primary=True)
