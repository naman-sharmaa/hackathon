"""
session_state.py — per-session negotiation state + the round-advance logic.

Turn model: buyer speaks, then seller, alternating. Each `advance_turn()` call
produces exactly one side's message (autonomously via the agent, or from a
human-supplied text during a takeover), classifies it, validates it, updates the
canonical offer, and checks the stopping rules.

Human-override policy (decided once, documented in failure_log.md):
    A human message's price, if one is present, becomes that side's new
    canonical offer directly. The engine recomputes its own suggestion from
    there next round. If the human types no number, the engine's suggested
    number stands as the canonical offer for that turn.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict

from config import SETTINGS
from engine.concession_engine import next_offer, opening_offer
from engine.stopping_rules import check_stopping, is_terminal, AGREEMENT, WALK_AWAY, MAX_ROUNDS
from engine.validator import validate_message, extract_prices
from engine.tactic_classifier import classify
from agents.llm_client import LLMClient
from agents.buyer_agent import BuyerAgent
from agents.seller_agent import SellerAgent
from agents.fallback_agent import FallbackAgent
from control.context_builder import build_context


@dataclass
class Message:
    round: int
    side: str            # buyer | seller
    source: str          # agent | human
    content: str
    quoted_price: float | None = None
    detected_tactic: str | None = None
    tactic_confidence: float = 0.0
    validator_price_ok: bool = True
    validator_leak_detected: bool = False
    validator_details: str = ""
    backend: str = ""    # openrouter | ollama | mock | human (narration source)
    backend_reason: str = ""  # WHY this backend was used (e.g. why it degraded)
    timestamp: float = field(default_factory=time.time)

    def public(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class Intervention:
    side: str
    action: str          # take_over | return_to_ai
    round: int
    timestamp: float = field(default_factory=time.time)


class SessionState:
    def __init__(self, buyer_constraints: dict, seller_constraints: dict,
                 currency: str = "$", deadline_round: int | None = None,
                 tolerance: float | None = None, max_rounds: int | None = None,
                 title: str = "", property: dict | None = None,
                 buyer_control: str = "autopilot", budget_cap: float | None = None):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.currency = currency
        self.created_at = time.time()

        # The listing this negotiation is about (public summary only — never the
        # seller's floor). None for a bare/abstract negotiation.
        self.property = property

        # Constraints (reservation = buyer budget ceiling / seller floor).
        self.buyer_constraints = buyer_constraints
        self.seller_constraints = seller_constraints
        self.buyer_reservation = float(buyer_constraints["reservation_price"])
        self.seller_reservation = float(seller_constraints["reservation_price"])
        self.buyer_anchor = float(buyer_constraints.get("opening_offer")
                                  or opening_offer("buyer", self.buyer_reservation))
        self.seller_anchor = float(seller_constraints.get("opening_offer")
                                   or opening_offer("seller", self.seller_reservation))

        self.deadline_round = deadline_round
        self.tolerance = SETTINGS.engine.tolerance if tolerance is None else tolerance
        self.max_rounds = SETTINGS.engine.max_rounds if max_rounds is None else max_rounds

        # --- who's driving the BUYER side -----------------------------------
        # "autopilot": the buyer's AI agent negotiates but PAUSES for human
        #   approval at the gates below. "manual": the human types every buyer
        #   message from the start (the contractor/seller is always the AI).
        self.buyer_control = buyer_control if buyer_control in ("autopilot", "manual") else "autopilot"
        # Optional soft ceiling: if the engine's proposed buyer offer would
        # exceed this, pause for approval even though it's under the budget.
        self.budget_cap = float(budget_cap) if budget_cap is not None else None
        # When a gate trips in autopilot, the pending decision lives here and
        # the negotiation blocks until the human resolves it.
        self.pending_approval: dict | None = None
        self.approval_log: list[dict] = []

        # Live state.
        self.status = "active"                 # active | agreed | walked_away | max_rounds
        self.turn = "buyer"                    # buyer goes first
        self.exchange = 0                      # completed buyer+seller exchanges
        self.round_count = {"buyer": 0, "seller": 0}
        self.mode = {"buyer": "auto", "seller": "auto"}
        if self.buyer_control == "manual":
            self.mode["buyer"] = "human"       # human drives the buyer from turn 1
        self.offer = {"buyer": None, "seller": None}
        self.fallback_active = {"buyer": False, "seller": False}
        self.history: list[Message] = []
        self.interventions: list[Intervention] = []
        self.final_price: float | None = None

        # Agents share one client (so circuit-breaker state is per session).
        self.client = LLMClient()
        self.agents = {
            "buyer": BuyerAgent(self.client, currency=currency,
                                persona_extra=buyer_constraints.get("persona", "")),
            "seller": SellerAgent(self.client, currency=currency,
                                  persona_extra=seller_constraints.get("persona", "")),
        }

    # ------------------------------------------------------------------ #
    def _reservation(self, side: str) -> float:
        return self.buyer_reservation if side == "buyer" else self.seller_reservation

    def _anchor(self, side: str) -> float:
        return self.buyer_anchor if side == "buyer" else self.seller_anchor

    def _last_counterparty_tactic(self, side: str) -> str | None:
        other = "seller" if side == "buyer" else "buyer"
        for m in reversed(self.history):
            if m.side == other:
                return m.detected_tactic
        return None

    def compute_engine_offer(self, side: str) -> float:
        """The deterministic next number for `side` this turn."""
        other = "seller" if side == "buyer" else "buyer"
        rnum = self.round_count[side] + 1
        return next_offer(
            side=side,
            round_num=rnum,
            reservation_price=self._reservation(side),
            counterparty_last_offer=self.offer[other],
            tactic=self._last_counterparty_tactic(side),
            deadline_round=self.deadline_round,
            opening_anchor=self._anchor(side),
        )

    # ------------------------------------------------------------------ #
    def _fmt(self, amount: float | None) -> str:
        if amount is None:
            return "—"
        return f"{self.currency}{amount:,.0f}"

    def _approval_gates(self, engine_offer: float) -> list[dict]:
        """Which human-approval gates does the buyer's *proposed* move trip?

        Only meaningful for the buyer on autopilot. Returns a (possibly empty)
        list of {type, detail} — an empty list means "proceed without asking".
        """
        gates: list[dict] = []
        seller_offer = self.offer["seller"]

        # (1) Closing gate — would this buyer move actually settle the deal?
        if seller_offer is not None:
            outcome = check_stopping(
                engine_offer, seller_offer, self.exchange or 1,
                tolerance=self.tolerance, max_rounds=self.max_rounds,
                deadline_round=self.deadline_round,
            )
            if outcome == AGREEMENT:
                settle = round((engine_offer + seller_offer) / 2.0)
                gates.append({
                    "type": "close",
                    "detail": f"This move closes the deal at about {self._fmt(settle)}.",
                })

        # (2) Hard-demand gate — the contractor's last message pressed hard.
        seller_tactic = self._last_counterparty_tactic("buyer")
        if seller_tactic in ("walk_away_threat", "deadline_pressure"):
            label = ("a walk-away threat" if seller_tactic == "walk_away_threat"
                     else "deadline pressure")
            gates.append({
                "type": "hard_demand",
                "detail": f"The contractor is using {label}. Decide how to respond.",
            })

        # (3) Budget-cap gate — proposed offer exceeds the soft cap you set.
        if self.budget_cap is not None and engine_offer > self.budget_cap:
            gates.append({
                "type": "over_budget",
                "detail": (f"Proposed offer {self._fmt(engine_offer)} exceeds your "
                           f"approval cap of {self._fmt(self.budget_cap)}."),
            })
        return gates

    def _needs_approval(self, side: str, engine_offer: float) -> list[dict]:
        """Gate only the buyer while it's genuinely on autopilot."""
        if side != "buyer" or self.buyer_control != "autopilot":
            return []
        if self.mode["buyer"] != "auto":   # human has taken the wheel already
            return []
        return self._approval_gates(engine_offer)

    # ------------------------------------------------------------------ #
    def advance_turn(self, human_message: str | None = None,
                     _bypass_approval: bool = False) -> dict:
        """Advance exactly one turn. If the current side is in human mode,
        `human_message` must be supplied. If the buyer is on autopilot and the
        proposed move trips an approval gate, this STOPS and records a pending
        approval instead of speaking (unless `_bypass_approval` is set, which is
        how an approved decision resumes)."""
        if is_terminal(self.status if self.status != "active" else "continue"):
            return {"error": "session already ended", "status": self.status}
        if self.pending_approval is not None and not _bypass_approval:
            return {"error": "waiting on human approval",
                    "status": self.status, "awaiting_approval": True,
                    "pending_approval": self.pending_approval}

        side = self.turn
        rnum = self.round_count[side] + 1
        engine_offer = self.compute_engine_offer(side)
        new_messages: list[Message] = []

        # Human-in-the-loop: stop before an autopilot buyer move that needs a nod.
        if not _bypass_approval:
            gates = self._needs_approval(side, engine_offer)
            if gates:
                self.pending_approval = {
                    "side": side,
                    "round": rnum,
                    "gates": gates,
                    "proposed_offer": engine_offer,
                    "proposed_offer_display": self._fmt(engine_offer),
                    "seller_offer": self.offer["seller"],
                    "seller_last_message": self._last_message_text("seller"),
                }
                return {
                    "session_id": self.id,
                    "status": self.status,
                    "turn": self.turn,
                    "offers": dict(self.offer),
                    "final_price": self.final_price,
                    "messages": [],
                    "awaiting_approval": True,
                    "pending_approval": self.pending_approval,
                }

        if self.mode[side] == "human":
            if human_message is None:
                return {"error": f"{side} is in human mode; a message is required",
                        "status": self.status, "awaiting_human": side}
            msg = self._make_human_message(side, rnum, human_message, engine_offer)
        else:
            msg = self._make_agent_message(side, rnum, engine_offer)

        self.history.append(msg)
        new_messages.append(msg)
        self.offer[side] = msg.quoted_price if msg.quoted_price is not None else engine_offer
        self.round_count[side] += 1

        # Flip the turn; count a completed exchange after each seller turn.
        self.turn = "seller" if side == "buyer" else "buyer"
        if side == "seller":
            self.exchange += 1

        # Stopping check once both sides have an offer on the table.
        status = self._check_and_finalize(closing_side=self.turn)
        if status != "active":
            # Append a single closing narration for a clean transcript.
            closer = self._make_closing_message(status)
            if closer:
                self.history.append(closer)
                new_messages.append(closer)

        return {
            "session_id": self.id,
            "status": self.status,
            "turn": self.turn,
            "offers": dict(self.offer),
            "final_price": self.final_price,
            "messages": [m.public() for m in new_messages],
            "awaiting_human": self.turn if self.mode[self.turn] == "human" and self.status == "active" else None,
        }

    # ------------------------------------------------------------------ #
    def _last_message_text(self, side: str) -> str:
        for m in reversed(self.history):
            if m.side == side:
                return m.content
        return ""

    def resolve_approval(self, decision: str, message: str | None = None) -> dict:
        """Human resolves a pending approval.

          approve   -> perform the proposed buyer move (may close the deal).
          counter   -> the human takes the wheel and sends `message` themselves;
                       the buyer stays under human control until handed back.
          walk      -> the buyer declines and the negotiation ends.
        """
        pa = self.pending_approval
        if pa is None:
            return {"error": "no pending approval", "status": self.status}
        decision = (decision or "").lower()
        self.approval_log.append({"decision": decision, "gates": pa["gates"],
                                  "round": pa["round"], "timestamp": time.time()})

        if decision in ("approve", "accept", "yes"):
            self.pending_approval = None
            return self.advance_turn(_bypass_approval=True)

        if decision in ("counter", "take_over", "intervene", "myself"):
            self.mode["buyer"] = "human"
            self.interventions.append(Intervention(side="buyer", action="take_over",
                                                    round=self.exchange))
            self.pending_approval = None
            if message is None or not str(message).strip():
                # Just hand the wheel over; wait for the human to type.
                return {
                    "session_id": self.id, "status": self.status, "turn": self.turn,
                    "offers": dict(self.offer), "final_price": self.final_price,
                    "messages": [], "awaiting_human": self.turn,
                }
            return self.advance_turn(human_message=message, _bypass_approval=True)

        if decision in ("walk", "walk_away", "decline", "reject", "no"):
            self.pending_approval = None
            return self._buyer_declines()

        # Unknown decision — keep the pending approval intact.
        self.approval_log.pop()
        return {"error": f"unknown decision {decision!r}", "status": self.status,
                "awaiting_approval": True, "pending_approval": pa}

    def _buyer_declines(self) -> dict:
        """The human chose to walk. End the negotiation cleanly, buyer-side."""
        side = "buyer"
        rnum = self.round_count[side] + 1
        msg = Message(
            round=rnum, side=side, source="human",
            content=("I appreciate the time, but this isn't going to work for me at "
                     "that price. I'll pass for now — thanks."),
            quoted_price=None, detected_tactic="walk_away_threat",
            tactic_confidence=0.9, backend="human",
        )
        self.history.append(msg)
        self.round_count[side] += 1
        self.status = "walked_away"
        self.turn = "seller"
        return {
            "session_id": self.id, "status": self.status, "turn": self.turn,
            "offers": dict(self.offer), "final_price": self.final_price,
            "messages": [msg.public()], "awaiting_human": None,
        }

    def maybe_auto_reply(self) -> list[dict]:
        """Advance exactly one turn IF the side to move is the AI and nothing
        is blocking — used to give the contractor an immediate reply after a
        human buyer message, so manual chat feels conversational."""
        if (self.status == "active" and self.mode[self.turn] == "auto"
                and self.pending_approval is None):
            r = self.advance_turn()
            if "error" not in r:
                return r.get("messages", [])
        return []

    # ------------------------------------------------------------------ #
    def _make_agent_message(self, side: str, rnum: int, engine_offer: float) -> Message:
        ctx = build_context(self.history, for_side=side)
        counter_tactic = self._last_counterparty_tactic(side)
        result = self.agents[side].respond(ctx, engine_offer, counter_tactic, rnum, mode="offer")

        # Explicit fallback swap on a tripped breaker (visible + demoable).
        if self.client.breakers[side].is_open and not self.fallback_active[side]:
            self.fallback_active[side] = True
            self.agents[side] = FallbackAgent(side, self.client, currency=self.currency)

        tactic = classify(result.text)
        v = validate_message(result.text, side, rnum, engine_offer,
                             self._reservation(side), source="agent")
        return Message(
            round=rnum, side=side, source="agent", content=result.text,
            quoted_price=engine_offer,
            detected_tactic=tactic.ensemble_label,
            tactic_confidence=tactic.ensemble_confidence,
            validator_price_ok=v.price_ok,
            validator_leak_detected=v.leak_detected,
            validator_details=v.details,
            backend=result.backend,
            backend_reason=result.reason,
        )

    def _make_human_message(self, side: str, rnum: int, text: str, engine_offer: float) -> Message:
        prices = extract_prices(text)
        # Human-override: a stated price becomes the canonical offer directly.
        canonical = None
        if prices:
            # Choose the price closest to a sensible range (nearest to engine).
            canonical = min(prices, key=lambda p: abs(p - engine_offer))
        tactic = classify(text)
        v = validate_message(text, side, rnum, engine_offer, self._reservation(side),
                             source="human")
        return Message(
            round=rnum, side=side, source="human", content=text,
            quoted_price=canonical,   # None if the human typed no number
            detected_tactic=tactic.ensemble_label,
            tactic_confidence=tactic.ensemble_confidence,
            validator_price_ok=v.price_ok,
            validator_leak_detected=v.leak_detected,
            validator_details=v.details,
            backend="human",
        )

    def _check_and_finalize(self, closing_side: str) -> str:
        if self.offer["buyer"] is None or self.offer["seller"] is None:
            return "active"
        outcome = check_stopping(
            self.offer["buyer"], self.offer["seller"], self.exchange or 1,
            tolerance=self.tolerance, max_rounds=self.max_rounds,
            deadline_round=self.deadline_round,
        )
        if outcome == AGREEMENT:
            self.status = "agreed"
            self.final_price = round((self.offer["buyer"] + self.offer["seller"]) / 2.0, 2)
        elif outcome == WALK_AWAY:
            self.status = "walked_away"
        elif outcome == MAX_ROUNDS:
            self.status = "max_rounds"
        return self.status

    def _make_closing_message(self, status: str) -> Message | None:
        # The side that would speak next narrates the close.
        side = self.turn
        rnum = self.round_count[side] + 1
        if status == "agreed":
            ctx = build_context(self.history, for_side=side)
            result = self.agents[side].respond(ctx, self.final_price, None, rnum, mode="accept")
            v = validate_message(result.text, side, rnum, self.final_price,
                                 self._reservation(side), source="agent")
            return Message(round=rnum, side=side, source="agent", content=result.text,
                           quoted_price=self.final_price,
                           validator_price_ok=v.price_ok,
                           validator_leak_detected=v.leak_detected,
                           validator_details=v.details, backend=result.backend,
                           backend_reason=result.reason,
                           detected_tactic="concession", tactic_confidence=0.9)
        if status in ("walked_away", "max_rounds"):
            ctx = build_context(self.history, for_side=side)
            result = self.agents[side].respond(ctx, None, None, rnum, mode="walk")
            v = validate_message(result.text, side, rnum, None,
                                 self._reservation(side), source="agent")
            return Message(round=rnum, side=side, source="agent", content=result.text,
                           quoted_price=None,
                           validator_price_ok=v.price_ok,
                           validator_leak_detected=v.leak_detected,
                           validator_details=v.details, backend=result.backend,
                           backend_reason=result.reason,
                           detected_tactic="walk_away_threat", tactic_confidence=0.9)
        return None

    # ------------------------------------------------------------------ #
    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "currency": self.currency,
            "property": self.property,
            "status": self.status,
            "turn": self.turn,
            "exchange": self.exchange,
            "mode": dict(self.mode),
            "buyer_control": self.buyer_control,
            "budget_cap": self.budget_cap,
            "offers": dict(self.offer),
            "final_price": self.final_price,
            "deadline_round": self.deadline_round,
            "max_rounds": self.max_rounds,
            "tolerance": self.tolerance,
            "fallback_active": dict(self.fallback_active),
            "circuit_open": {s: b.is_open for s, b in self.client.breakers.items()},
            "narration_reason": dict(self.client.last_reason),
            "live_llm": bool(SETTINGS.has_openrouter),
            "pending_approval": self.pending_approval,
            "approval_log": self.approval_log,
            "history": [m.public() for m in self.history],
            "interventions": [asdict(i) for i in self.interventions],
            "awaiting_approval": self.pending_approval is not None,
            "awaiting_human": (self.turn if self.mode[self.turn] == "human"
                               and self.status == "active"
                               and self.pending_approval is None else None),
        }
