"""
tactic_classifier.py — hybrid negotiation-tactic detection.

Returns, for one incoming message:
  * rule_label / rule_confidence   — keyword+regex rules (deterministic)
  * llm_label  / llm_confidence    — a single CLASSIFIER_MODEL call, OR an
                                     offline semantic-scoring stand-in when no
                                     key is configured (clearly flagged)
  * ensemble_label / ensemble_conf — the spec's combiner: trust the rule when
                                     it fires with high confidence, else the LLM

Rule-only and LLM-only labels are logged separately so run_eval.py can produce
the rules-vs-LLM-vs-ensemble ablation (spec Section 6) — the project's single
strongest "technical depth" artifact.

If time-pressed, this module can be cut to rules-only (set USE_LLM=False) with
no effect on the engine/validator — see failure_log.md.  It is NOT one of the
never-cut modules.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from config import SETTINGS, TACTICS, TACTIC_DESCRIPTIONS

# Trust a firing rule over the LLM when its confidence clears this bar.
RULE_TRUST_THRESHOLD = 0.60
USE_LLM = True


@dataclass
class TacticResult:
    rule_label: str | None
    rule_confidence: float
    llm_label: str | None
    llm_confidence: float
    ensemble_label: str
    ensemble_confidence: float
    source: str            # 'rules' | 'llm'
    llm_backend: str       # 'openrouter' | 'offline-heuristic'
    scores: dict           # per-tactic rule score, for debugging/eval

    def to_row(self) -> dict:
        return {
            "detected_tactic": self.ensemble_label,
            "tactic_confidence": round(self.ensemble_confidence, 3),
        }


# ---------------------------------------------------------------------------
# Rule layer — strict, high-precision keyword/regex signals per tactic.
# Each entry: (compiled_regex, weight).  Weight reflects how unambiguous the
# signal is.  Confidence saturates as more/stronger signals fire.
# ---------------------------------------------------------------------------
def _p(*alts: str) -> re.Pattern:
    return re.compile("|".join(alts), re.IGNORECASE)


RULE_PATTERNS: dict[str, list[tuple[re.Pattern, float]]] = {
    "walk_away_threat": [
        (_p(r"\bwalk(?:ing)? away\b", r"\bdeal is off\b", r"\bi'?m out\b",
            r"\bfind (?:another|other)\b", r"\bother (?:buyers?|offers?|tenants?)\b",
            r"\blook elsewhere\b", r"\bmove on\b", r"\bcall (?:it|the whole thing) off\b"), 0.55),
    ],
    "comparables": [
        (_p(r"\bcomparable(?:s)?\b", r"\bcomps?\b", r"\bmarket rate\b",
            r"\bgoing rate\b", r"\bother (?:listings?|units?|places?|properties)\b",
            r"\bsimilar (?:units?|places?|properties|listings?)\b",
            r"\bdown the (?:street|block)\b", r"\bthe market\b", r"\baverage price\b"), 0.5),
    ],
    "splitting_difference": [
        (_p(r"\bmeet (?:in the middle|halfway|you (?:half|part)way)\b",
            r"\bsplit the difference\b", r"\bhalfway\b", r"\bcompromise\b",
            r"\bmeet you at\b"), 0.6),
    ],
    "deadline_pressure": [
        (_p(r"\bdeadline\b", r"\bexpires?\b", r"\btoday only\b",
            r"\bby (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|noon|tonight|end of (?:day|week))\b",
            r"\b24 hours\b", r"\brunning out of time\b", r"\boffer (?:stands|is good) (?:until|till)\b",
            r"\bneed (?:an answer|a decision) by\b", r"\bclos(?:e|ing) (?:by|before)\b"), 0.55),
    ],
    "silence": [
        (_p(r"\blet me think\b", r"\bget back to you\b", r"\bneed (?:some )?time\b",
            r"\bwe'?ll see\b", r"\bnot sure\b", r"\bconsider it\b", r"\bthink (?:it|this) over\b",
            r"\bno comment\b", r"\bmull it over\b"), 0.5),
    ],
    "concession": [
        (_p(r"\bi can come (?:down|up)\b", r"\bi'?ll (?:go|come) (?:up|down) to\b",
            r"\bwilling to (?:go|come|move|offer)\b", r"\bas a gesture\b",
            r"\bi can (?:do|offer)\b", r"\bmeet you\b", r"\blower my\b", r"\braise my\b",
            r"\bbest i can do\b", r"\bstretch to\b"), 0.4),
    ],
    "anchoring": [
        (_p(r"\btake it or leave it\b", r"\bthat'?s my (?:final |firm )?(?:price|number|offer)\b",
            r"\bfirm\b", r"\bnon[- ]?negotiable\b", r"\blist(?:ing)? price\b",
            r"\basking (?:price )?is\b", r"\bstarting (?:point|at)\b",
            r"\bwon'?t go (?:lower|higher) than\b"), 0.5),
    ],
    "flattery": [
        (_p(r"\bi (?:really )?appreciate\b", r"\bpleasure (?:doing|to)\b",
            r"\byou seem (?:reasonable|fair|nice)\b", r"\bi (?:love|like) (?:this|the) (?:place|property|unit)\b",
            r"\bi trust you\b", r"\bwe both want\b", r"\bno hard feelings\b"), 0.35),
    ],
}


def classify_rules(message: str) -> tuple[str | None, float, dict]:
    """High-precision rule pass. Returns (label|None, confidence, all_scores)."""
    scores: dict[str, float] = {t: 0.0 for t in TACTICS}
    for tactic, patterns in RULE_PATTERNS.items():
        for regex, weight in patterns:
            hits = len(regex.findall(message))
            if hits:
                # More matches => higher confidence, saturating below 1.0.
                scores[tactic] += weight + 0.1 * (hits - 1)
    best = max(scores, key=scores.get)
    if scores[best] <= 0:
        return None, 0.0, scores
    confidence = min(0.95, scores[best])
    return best, round(confidence, 3), scores


# ---------------------------------------------------------------------------
# LLM layer — one classifier call, or an offline semantic-scoring stand-in.
# ---------------------------------------------------------------------------
_LLM_SYS = (
    "You are a negotiation-tactic classifier. Read the single message and pick "
    "the ONE tactic label that best fits from this exact list:\n"
    + "\n".join(f"- {t}: {TACTIC_DESCRIPTIONS[t]}" for t in TACTICS)
    + "\n\nReturn ONLY compact JSON: {\"tactic\": \"<label>\", \"confidence\": <0..1>}. "
    "No prose, no markdown."
)

# Broader, softer synonym signals than the strict rules — deliberately catches
# things the rules miss, so the offline ablation isn't a trivial tie.
_SEMANTIC_HINTS: dict[str, list[str]] = {
    "walk_away_threat": ["leave", "gone", "elsewhere", "pass", "not interested", "waste", "done here"],
    "comparables": ["saw", "listed", "quote", "priced at", "next door", "neighbourhood", "neighborhood", "recently", "sold for"],
    "splitting_difference": ["middle", "between", "fair to both", "somewhere around", "call it"],
    "deadline_pressure": ["soon", "quick", "now", "urgent", "waiting", "hurry", "this week", "before"],
    "silence": ["hmm", "maybe", "perhaps", "later", "unsure", "dunno", "possibly"],
    "concession": ["okay", "alright", "fine", "budge", "flexible", "give a little", "work with you"],
    "anchoring": ["worth", "value", "premium", "priced", "won't budge", "standing firm", "bottom line is"],
    "flattery": ["thanks", "kind", "generous", "honest", "respect", "friend", "wonderful"],
}


def _offline_llm(message: str) -> tuple[str, float]:
    """Deterministic stand-in for the LLM classifier when no key is present.

    Scores soft synonym hits; intentionally different from the strict rules so
    the rules-vs-LLM-vs-ensemble ablation is meaningful even offline.  Flagged
    as 'offline-heuristic' so nobody mistakes it for a real model."""
    low = message.lower()
    scores = {t: 0.0 for t in TACTICS}
    for tactic, hints in _SEMANTIC_HINTS.items():
        for h in hints:
            if h in low:
                scores[tactic] += 0.34
    # Fold in a softened echo of the rule signals for stability.
    rlabel, rconf, rscores = classify_rules(message)
    for t, s in rscores.items():
        scores[t] += 0.4 * s
    best = max(scores, key=scores.get)
    if scores[best] <= 0:
        return "neutral", 0.4
    return best, round(min(0.9, 0.45 + scores[best] / 3.0), 3)


def classify_llm(message: str) -> tuple[str, float, str]:
    """Returns (label, confidence, backend). Uses OpenRouter when configured,
    else the offline heuristic. Never raises — a failed call degrades to the
    heuristic so classification is always available."""
    if not USE_LLM:
        return "neutral", 0.0, "disabled"
    if SETTINGS.has_openrouter:
        try:
            from agents.llm_client import chat_once  # lazy: avoids import cycle
            raw = chat_once(
                model=SETTINGS.classifier_model,
                messages=[{"role": "system", "content": _LLM_SYS},
                          {"role": "user", "content": message}],
                max_tokens=40, temperature=0.0,
            )
            label, conf = _parse_llm_json(raw)
            if label in TACTICS:
                return label, conf, "openrouter"
        except Exception:
            pass  # fall through to heuristic
    label, conf = _offline_llm(message)
    return label, conf, "offline-heuristic"


def _parse_llm_json(raw: str) -> tuple[str, float]:
    # Be forgiving: pull the first {...} block out of whatever the model said.
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return "neutral", 0.3
    try:
        obj = json.loads(m.group(0))
        return str(obj.get("tactic", "neutral")).strip(), float(obj.get("confidence", 0.5))
    except (json.JSONDecodeError, ValueError, TypeError):
        return "neutral", 0.3


# ---------------------------------------------------------------------------
# Ensemble
# ---------------------------------------------------------------------------
def classify(message: str) -> TacticResult:
    rule_label, rule_conf, scores = classify_rules(message)
    llm_label, llm_conf, backend = classify_llm(message)

    if rule_label is not None and rule_conf >= RULE_TRUST_THRESHOLD:
        ensemble_label, ensemble_conf, source = rule_label, rule_conf, "rules"
    elif rule_label is not None and rule_label == llm_label:
        # Agreement between a weak rule and the LLM boosts confidence.
        ensemble_label = rule_label
        ensemble_conf = min(0.95, max(rule_conf, llm_conf) + 0.1)
        source = "rules"
    else:
        ensemble_label, ensemble_conf, source = llm_label, llm_conf, "llm"

    return TacticResult(
        rule_label=rule_label,
        rule_confidence=rule_conf,
        llm_label=llm_label,
        llm_confidence=llm_conf,
        ensemble_label=ensemble_label,
        ensemble_confidence=ensemble_conf,
        source=source,
        llm_backend=backend,
        scores=scores,
    )
