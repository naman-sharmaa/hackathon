"""buyer_agent.py — the Buyer persona (uses BUYER_MODEL via llm_client)."""
from __future__ import annotations

from agents.base_agent import BaseAgent
from agents.llm_client import LLMClient


class BuyerAgent(BaseAgent):
    def __init__(self, client: LLMClient, currency: str = "$", persona_extra: str = ""):
        super().__init__("buyer", client, currency=currency, persona_extra=persona_extra)
