"""
run_eval.py — DealBench evaluation harness (spec Section 6).

Runs entirely offline (no API key required) and reports the five metrics the
spec asks a judge to see, writing a timestamped snapshot to eval_results.json
({"latest": ..., "history": [...]}) that the eval dashboard reads:

  1. Tactic-classification accuracy + macro-F1, as a rules-vs-LLM-vs-ensemble
     ABLATION (the project's headline "technical depth" artifact).
  2. Price-consistency pass rate across full auto-negotiations.
  3. Reservation-leak detection: miss-rate on real leaks (target 0%) and
     false-positive rate on safe messages (target 0%).
  4. Stopping-rule accuracy on scripted scenarios.
  5. Fallback-trigger success rate — simulated API timeouts / malformed
     responses that must degrade gracefully and keep the session alive.

Run:  python run_eval.py         (from backend/eval, or anywhere)
"""
from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path
from statistics import mean

# --- make the backend package importable no matter where we're launched -----
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402
from config import EVAL_DIR, TACTICS  # noqa: E402
from engine.tactic_classifier import classify, classify_rules, classify_llm  # noqa: E402
from engine.validator import validate_message  # noqa: E402
from engine.stopping_rules import (  # noqa: E402
    check_stopping, AGREEMENT, WALK_AWAY, MAX_ROUNDS, CONTINUE,
)

RESULTS_PATH = EVAL_DIR / "eval_results.json"


def _load(name: str) -> dict:
    return json.loads((EVAL_DIR / name).read_text(encoding="utf-8"))


# ===========================================================================
# Test-double plumbing for the fallback scenarios
# ===========================================================================
@contextlib.contextmanager
def patched_settings(**over):
    """Temporarily override fields on the shared (frozen) Settings object.

    Modules did `from config import SETTINGS`, so they share this one instance;
    bypassing the frozen guard with object.__setattr__ flips their view too."""
    S = config.SETTINGS
    saved = {k: getattr(S, k) for k in over}
    for k, v in over.items():
        object.__setattr__(S, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            object.__setattr__(S, k, v)


@contextlib.contextmanager
def patched(attr: str, func):
    """Swap a module-global in agents.llm_client (looked up at call time)."""
    import agents.llm_client as lc
    saved = getattr(lc, attr)
    setattr(lc, attr, func)
    try:
        yield
    finally:
        setattr(lc, attr, saved)


def _boom_openrouter(*_a, **_k):
    from agents.llm_client import OpenRouterError
    raise OpenRouterError("transport error: simulated timeout")


def _malformed_openrouter(*_a, **_k):
    from agents.llm_client import OpenRouterError
    raise OpenRouterError("malformed response: {'unexpected': True}")


def _boom_ollama(*_a, **_k):
    raise OSError("simulated: ollama not running")


def _fresh_client():
    from agents.llm_client import LLMClient
    return LLMClient()


def _narrate(client, side="buyer", engine_offer=17400.0, rn=1):
    return client.narrate(side, "You are a negotiator.", [], engine_offer,
                          "neutral", rn, mode="offer", currency="$")


# ===========================================================================
# Metric 1 — tactic classification ablation (rules vs LLM vs ensemble)
# ===========================================================================
def _macro_f1(gold_primary: list[str], pred: list[str]) -> tuple[float, dict]:
    """Standard multiclass macro-F1 against each example's PRIMARY gold label.
    Only labels that actually occur in the gold set are averaged (fair macro)."""
    per = {}
    for t in TACTICS:
        tp = sum(1 for g, p in zip(gold_primary, pred) if p == t and g == t)
        fp = sum(1 for g, p in zip(gold_primary, pred) if p == t and g != t)
        fn = sum(1 for g, p in zip(gold_primary, pred) if p != t and g == t)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per[t] = {"precision": round(prec, 3), "recall": round(rec, 3),
                  "f1": round(f1, 3), "support": tp + fn}
    present = [t for t in TACTICS if per[t]["support"] > 0]
    macro = round(mean(per[t]["f1"] for t in present), 3) if present else 0.0
    return macro, per


def eval_tactics() -> dict:
    data = _load("eval_transcripts.json")["examples"]
    gold_sets = [set(ex["tactic_label"].split("+")) for ex in data]
    gold_primary = [ex["tactic_label"].split("+")[0] for ex in data]

    preds = {"rules": [], "llm": [], "ensemble": []}
    llm_backend = "n/a"
    for ex in data:
        msg = ex["message"]
        rl, _rc, _ = classify_rules(msg)
        preds["rules"].append(rl or "neutral")
        ll, _lc, backend = classify_llm(msg)
        preds["llm"].append(ll)
        llm_backend = backend
        preds["ensemble"].append(classify(msg).ensemble_label)

    out = {"n_examples": len(data), "llm_backend": llm_backend, "systems": {}}
    for sys_name, plist in preds.items():
        # Lenient accuracy: credit a prediction that hits ANY gold component
        # (compound-labelled messages genuinely use >1 tactic).
        acc = mean(1.0 if p in gs else 0.0 for p, gs in zip(plist, gold_sets))
        macro, per = _macro_f1(gold_primary, plist)
        out["systems"][sys_name] = {
            "accuracy": round(acc, 3),
            "macro_f1": macro,
            "per_label_f1": per,
        }
    return out


# ===========================================================================
# Metric 2 — price consistency across full auto-negotiations
# ===========================================================================
_NEGOTIATIONS = [
    {"name": "wide ZOPA", "buyer_res": 20000, "seller_res": 15000, "deadline": None},
    {"name": "narrow ZOPA", "buyer_res": 18000, "seller_res": 16000, "deadline": None},
    {"name": "deadline pressure", "buyer_res": 25000, "seller_res": 20000, "deadline": 8},
    {"name": "no ZOPA (no deal)", "buyer_res": 14000, "seller_res": 15000, "deadline": None},
    {"name": "high-value deal", "buyer_res": 30000, "seller_res": 22000, "deadline": None},
]


def _run_negotiation(spec: dict):
    from control.session_state import SessionState
    s = SessionState(
        buyer_constraints={"reservation_price": spec["buyer_res"]},
        seller_constraints={"reservation_price": spec["seller_res"]},
        currency="$", deadline_round=spec["deadline"], title=spec["name"],
    )
    guard = 0
    while s.status == "active" and guard < 60:
        s.advance_turn()
        guard += 1
    return s


def eval_price_consistency() -> dict:
    checked = passed = leaks = 0
    outcomes = {}
    # Offline so the mock narrator embeds the engine number deterministically —
    # price-consistency is then a property of the whole pipeline, not luck.
    with patched_settings(offline=True):
        for spec in _NEGOTIATIONS:
            s = _run_negotiation(spec)
            outcomes[spec["name"]] = {"status": s.status, "final_price": s.final_price}
            for m in s.history:
                if m.source != "agent":
                    continue
                checked += 1
                if m.validator_price_ok:
                    passed += 1
                if m.validator_leak_detected:
                    leaks += 1
    return {
        "agent_messages_checked": checked,
        "passed": passed,
        "pass_rate": round(passed / checked, 4) if checked else 0.0,
        "agent_leaks_during_play": leaks,
        "outcomes": outcomes,
    }


# ===========================================================================
# Metric 3 — reservation-leak detection
# ===========================================================================
def eval_leaks() -> dict:
    attempts = _load("eval_leak_attempts.json")["attempts"]
    real_leaks = [a for a in attempts if a["should_detect"]]
    safe = [a for a in attempts if not a["should_detect"]]

    missed, false_pos = [], []
    for a in attempts:
        v = validate_message(a["message"], side="buyer", round_num=3,
                             engine_offer=None, reservation_price=a["reservation_price"],
                             source=a["source"])
        if a["should_detect"] and not v.leak_detected:
            missed.append(a["name"])
        if (not a["should_detect"]) and v.leak_detected:
            false_pos.append(a["name"])

    return {
        "total_attempts": len(attempts),
        "real_leaks": len(real_leaks),
        "safe_messages": len(safe),
        "leak_miss_rate": round(len(missed) / len(real_leaks), 4) if real_leaks else 0.0,
        "leak_recall": round(1 - len(missed) / len(real_leaks), 4) if real_leaks else 1.0,
        "false_positive_rate": round(len(false_pos) / len(safe), 4) if safe else 0.0,
        "missed_leaks": missed,
        "false_positives": false_pos,
    }


# ===========================================================================
# Metric 4 — stopping-rule accuracy
# ===========================================================================
_ACTION_MAP = {"accept": AGREEMENT, "agreement": AGREEMENT,
               "walk_away": WALK_AWAY, "max_rounds": MAX_ROUNDS, "continue": CONTINUE}


def eval_stopping() -> dict:
    data = _load("eval_stopping_cases.json")
    tol, maxr = data["tolerance"], data["max_rounds"]
    correct, wrong = 0, []
    for c in data["cases"]:
        expected = _ACTION_MAP[c["expected_action"]]
        got = check_stopping(
            c["buyer_offer"], c["seller_offer"], c["round"],
            tolerance=tol, max_rounds=maxr,
            deadline_round=(c["round"] if c.get("deadline_hit") else None),
        )
        if got == expected:
            correct += 1
        else:
            wrong.append({"case": c["name"], "expected": expected, "got": got})
    n = len(data["cases"])
    return {"total": n, "correct": correct,
            "accuracy": round(correct / n, 4) if n else 0.0, "mistakes": wrong}


# ===========================================================================
# Metric 5 — fallback-trigger success (simulated failures)
# ===========================================================================
def _scenario(name: str) -> dict:
    """Reproduce one failure mode; return {backend, survived, breaker_tripped}."""
    if name == "offline_no_key":
        with patched_settings(openrouter_api_key="", offline=True):
            c = _fresh_client()
            r = _narrate(c)
            return {"backend": r.backend, "survived": bool(r.text),
                    "breaker_tripped": c.breakers["buyer"].tripped}

    if name == "openrouter_timeout_trips_breaker":
        with patched_settings(openrouter_api_key="sk-fake", offline=False, max_retries=1), \
             patched("_openrouter_chat", _boom_openrouter), \
             patched("_ollama_chat", _boom_ollama):
            c = _fresh_client()
            _narrate(c)          # failure #1
            r = _narrate(c)      # failure #2 -> breaker trips, then mock
            return {"backend": r.backend, "survived": bool(r.text),
                    "breaker_tripped": c.breakers["buyer"].tripped}

    if name == "malformed_response":
        with patched_settings(openrouter_api_key="sk-fake", offline=False, max_retries=1), \
             patched("_openrouter_chat", _malformed_openrouter), \
             patched("_ollama_chat", _boom_ollama):
            c = _fresh_client()
            r = _narrate(c)
            return {"backend": r.backend, "survived": bool(r.text),
                    "breaker_tripped": c.breakers["buyer"].tripped}

    if name == "intermittent_then_recover":
        state = {"n": 0}

        def flaky(*_a, **_k):
            state["n"] += 1
            if state["n"] == 1:
                from agents.llm_client import OpenRouterError
                raise OpenRouterError("transport error: transient")
            return "Alright, I'll come up to $17,400."
        with patched_settings(openrouter_api_key="sk-fake", offline=False, max_retries=3), \
             patched("_openrouter_chat", flaky):
            c = _fresh_client()
            r = _narrate(c)
            return {"backend": r.backend, "survived": bool(r.text),
                    "breaker_tripped": c.breakers["buyer"].tripped}

    if name == "full_negotiation_survives_failures":
        with patched_settings(openrouter_api_key="sk-fake", offline=False, max_retries=1), \
             patched("_openrouter_chat", _boom_openrouter), \
             patched("_ollama_chat", _boom_ollama):
            s = _run_negotiation({"name": "failure-storm", "buyer_res": 20000,
                                  "seller_res": 15000, "deadline": None})
            agent_backends = {m.backend for m in s.history if m.source == "agent"}
            backend = "mock" if agent_backends == {"mock"} else "mixed:" + ",".join(sorted(agent_backends))
            tripped = any(b.tripped for b in s.client.breakers.values())
            # "survived" = the negotiation still reached a clean terminal outcome
            # despite every model call failing. Session statuses are
            # agreed/walked_away/max_rounds (not the stopping-rule constants).
            return {"backend": backend, "survived": s.status != "active",
                    "breaker_tripped": tripped}

    raise ValueError(f"unknown scenario {name}")


def eval_fallback() -> dict:
    cases = _load("eval_failure_cases.json")["cases"]
    results, passed = [], 0
    for c in cases:
        got = _scenario(c["scenario"])
        ok = (got["survived"] == c["expect_survives"]
              and got["backend"] == c["expect_backend"]
              and got["breaker_tripped"] == c["expect_breaker_tripped"])
        passed += int(ok)
        results.append({"name": c["name"], "scenario": c["scenario"],
                        "pass": ok, "expected": {
                            "survived": c["expect_survives"],
                            "backend": c["expect_backend"],
                            "breaker_tripped": c["expect_breaker_tripped"]},
                        "got": got})
    n = len(cases)
    return {"total": n, "passed": passed,
            "success_rate": round(passed / n, 4) if n else 0.0, "cases": results}


# ===========================================================================
# Orchestration
# ===========================================================================
def run_all() -> dict:
    tactics = eval_tactics()
    price = eval_price_consistency()
    leaks = eval_leaks()
    stopping = eval_stopping()
    fallback = eval_fallback()

    # Headline pass/fail gates a judge can scan in one second.
    gates = {
        "no_leaks_missed": leaks["leak_miss_rate"] == 0.0,
        "no_false_positive_leaks": leaks["false_positive_rate"] == 0.0,
        "price_consistency_ok": price["pass_rate"] >= 0.99,
        "stopping_rules_perfect": stopping["accuracy"] == 1.0,
        "all_fallbacks_survived": fallback["success_rate"] == 1.0,
        "ensemble_best_or_tied": (
            tactics["systems"]["ensemble"]["accuracy"]
            >= max(tactics["systems"]["rules"]["accuracy"],
                   tactics["systems"]["llm"]["accuracy"]) - 1e-9
        ),
    }
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "offline_mode": not config.SETTINGS.has_openrouter,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "metrics": {
            "tactic_classification": tactics,
            "price_consistency": price,
            "leak_detection": leaks,
            "stopping_rules": stopping,
            "fallback_triggers": fallback,
        },
    }


def _write_results(latest: dict) -> str:
    payload = {"latest": latest, "history": []}
    if RESULTS_PATH.exists():
        try:
            prev = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
            payload["history"] = (prev.get("history", []) + [prev["latest"]])[-25:] \
                if "latest" in prev else prev.get("history", [])
        except (json.JSONDecodeError, OSError, KeyError):
            payload["history"] = []
    try:
        RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(RESULTS_PATH)
    except OSError:
        import tempfile
        alt = Path(tempfile.gettempdir()) / "eval_results.json"
        alt.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(alt)


def _print_summary(r: dict) -> None:
    t = r["metrics"]["tactic_classification"]["systems"]
    p = r["metrics"]["price_consistency"]
    lk = r["metrics"]["leak_detection"]
    st = r["metrics"]["stopping_rules"]
    fb = r["metrics"]["fallback_triggers"]
    print("\n" + "=" * 66)
    print(f"  DealBench eval  ({r['generated_at']}, "
          f"{'OFFLINE' if r['offline_mode'] else 'LIVE'} mode)")
    print("=" * 66)
    print("\n  1. Tactic classification (accuracy / macro-F1) — ablation:")
    for name in ("rules", "llm", "ensemble"):
        s = t[name]
        print(f"       {name:<9} acc={s['accuracy']:.3f}   macroF1={s['macro_f1']:.3f}")
    print(f"       (llm backend: {r['metrics']['tactic_classification']['llm_backend']})")
    print(f"\n  2. Price consistency:  {p['pass_rate']*100:.1f}%  "
          f"({p['passed']}/{p['agent_messages_checked']} agent msgs)")
    print(f"  3. Leak detection:     recall={lk['leak_recall']*100:.1f}%  "
          f"miss={lk['leak_miss_rate']*100:.1f}%  "
          f"false-pos={lk['false_positive_rate']*100:.1f}%")
    print(f"  4. Stopping rules:     {st['accuracy']*100:.1f}%  "
          f"({st['correct']}/{st['total']})")
    print(f"  5. Fallback triggers:  {fb['success_rate']*100:.1f}%  "
          f"({fb['passed']}/{fb['total']} scenarios)")
    print("\n  Gates:")
    for k, v in r["gates"].items():
        print(f"       [{'PASS' if v else 'FAIL'}] {k}")
    print("\n  " + ("ALL GATES PASS ✓" if r["all_gates_pass"] else "SOME GATES FAILED ✗"))
    print("=" * 66 + "\n")


def main() -> int:
    r = run_all()
    _print_summary(r)
    where = _write_results(r)
    print(f"  wrote {where}\n")
    return 0 if r["all_gates_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
