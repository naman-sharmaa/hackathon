"""seller_agent.py — the Seller persona (uses SELLER_MODEL via llm_client).

SELLER_MODEL must be a DIFFERENT model family from BUYER_MODEL — that is the
"two models genuinely cooperating" constraint. The family split is enforced by
configuration (.env), not code."""
from __future__ import annotations

from agents.base_agent import BaseAgent
from agents.llm_client import LLMClient


class SellerAgent(BaseAgent):
    def __init__(self, client: LLMClient, currency: str = "$", persona_extra: str = ""):
        super().__init__("seller", client, currency=currency, persona_extra=persona_extra)
