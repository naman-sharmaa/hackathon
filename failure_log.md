# failure_log.md

An honest engineering journal for DealBench: the decisions that weren't obvious, the things that broke during the build, and why the final design is shaped the way it is. Written for a judge who wants to know *why*, not just *what*.

---

## Decision 1 — The engine owns every number; the models only narrate

**Context.** The naive build is "give two LLMs the scenario and let them talk." It demos badly: models quote `$17,400` in one line and `$17,000` two lines later, they reveal their own walk-away price when pressed, and no two runs are the same.

**Decision.** All deal math is deterministic Python in `engine/`. Each turn, `concession_engine.next_offer()` produces the number; the agent is handed that number and asked only to phrase it. The fallback narrator literally string-checks that the number is present (`ensure_price_in_text`) before returning.

**Why.** It makes the three failure modes above *structurally impossible* rather than "usually fine." Price-consistency becomes a property of the pipeline, so the eval scores 100% offline by construction, not by prompt-luck.

**Trade-off.** The models have less creative latitude — they can't invent a clever new offer. That's the right trade for a benchmark: we're measuring negotiation *dynamics* and *narration fidelity*, not letting a model freestyle the economics.

---

## Decision 2 — Standard library only (no FastAPI, no pytest, no npm packages)

**Context.** The build sandbox has no package network at all: `pip install` and `npm install` both return `403 Forbidden`. Early attempt to `npm install react react-dom htm` to vendor the frontend failed outright.

**Decision.** Build the whole thing on the Python 3.10 standard library. The HTTP server is `http.server.ThreadingHTTPServer` with hand-rolled regex routing; the OpenRouter/Ollama client is `urllib`; persistence is `sqlite3`; the test runner is a ~40-line `run_tests.py` that discovers and runs test functions with no `pytest`.

**Why.** What started as a constraint is genuinely better for a hackathon deliverable: `git clone && python3 app.py` works on any machine with a stock Python, no install step, no lockfile drift, nothing to go wrong in front of a judge. The offline mock narrator means it even runs with no API key.

**Trade-off.** Single-process, hand-rolled routing, no async. Completely fine at demo scale; I'd reach for a framework only if this needed real concurrency.

---

## Decision 3 — Frontend is one file, React over CDN, no build step

**Context.** Same `npm` 403. The requested UI was "lightweight single-page React, no Next.js / no build."

**Decision.** `frontend/index.html` is a single file. React 18 + `htm` (tagged-template JSX alternative) load from the jsDelivr CDN, so there's no Babel and no bundler — components are written with `htm` template literals and rendered with `ReactDOM.createRoot`. All CSS is inline design tokens; the convergence chart is hand-drawn SVG/CSS (no Chart.js).

**Why.** Honors the "no build" ask and keeps the clone-and-run promise for the UI too. The single network dependency (the three CDN `<script>` tags) is documented in the README so it's not a surprise offline.

**Trade-off.** Needs network on first load for the CDN. Acceptable; everything else is self-contained.

---

## Decision 4 — Human-override policy: report price deviations, don't block them

**Context.** When a human takes over a side and types "I'll come up to 17,400," their number may not equal the engine's suggested number. What should the canonical offer become, and should a deviation be rejected?

**Decision.** The human's stated price (the one **nearest** the engine's suggestion, if several appear) becomes that side's canonical offer directly; the engine recomputes from there next round. If the human types no number, the engine's number stands. The validator still runs on the human's words exactly as for an AI turn, and a price that deviates from the engine's suggestion is **reported as a mismatch, not blocked**.

**Why.** A human takeover is an override by definition — silently discarding their number would be surprising and would defeat the purpose of the takeover. But we still want a record, so the report card surfaces the deviation. A reservation-price *leak*, by contrast, is always flagged loudly regardless of who wrote it.

**Trade-off.** A human can push the price to a value the engine wouldn't have chosen. That's intended: the point of the feature is to let a person steer. The report's "flags raised" stamp keeps it visible.

*(This is why a takeover run legitimately shows `clean=false` with a "price mismatch vs engine" note and zero leaks — that's correct behavior, not a bug.)*

---

## Decision 5 — Graceful-degradation ladder with a circuit breaker

**Context.** Free OpenRouter models are flaky and get delisted without notice. A live demo where the model call hangs is a dead demo.

**Decision.** Per side: `OpenRouter → Ollama → deterministic mock`, with exponential-backoff retries inside each attempt and a per-side **circuit breaker** that trips after N consecutive failures (default 2) and pins that side to the fallback for the rest of the session. The breaker state is visible in the session and the report ("degraded to fallback").

**Why.** The negotiation must always complete. Because the fallback still embeds the engine's number, degrading the narrator changes only the prose quality — the deal math, validation, and outcome are unaffected. This is directly exercised by the eval's five fallback scenarios (timeout-trips-breaker, malformed response, intermittent-then-recover, offline-no-key, full-negotiation-under-total-failure), all of which must survive.

**Trade-off.** Once a breaker trips it stays tripped for the session rather than probing for recovery. Simpler and more predictable for a demo than half-open retry logic.

---

## Decision 6 — Hybrid tactic classifier (rules ⊕ LLM), logged separately for ablation

**Context.** Tactic labeling could be pure regex (brittle) or pure LLM (imprecise, and unavailable offline).

**Decision.** High-precision regex rules fire first; when a rule matches with high confidence it wins, otherwise the LLM/offline-heuristic classifier decides. Crucially, the eval logs **rules-only, LLM-only, and ensemble predictions separately** so the benchmark can show the ablation.

**Why.** The ensemble beats both components (`acc 0.750` vs `0.708 / 0.708`), which is the empirical justification for the hybrid rather than an assertion. Keeping the three prediction streams separate is what lets a judge *see* that.

**Trade-off.** Two classifiers to maintain and keep label-aligned. Handled by making `config.TACTICS` the single source of truth that the rules, the LLM prompt, the eval labels, and the report card all import.

---

## Bugs found and fixed during verification

**`report` endpoint returned 500 — `Object of type LLMClient is not JSON serializable`.**
`report_card.degraded_to_fallback` was written as `A or B or (C and session.client)`; when the first parts were falsy, Python returned the `LLMClient` object itself, which then failed JSON encoding. Fixed by wrapping the whole expression in `bool(...)` and dropping the stray client term. Report now returns 200.

**Eval fallback scenario spuriously failed (4/5).** `full_negotiation_survives_failures` used `is_terminal(session.status)`, but session statuses are `agreed / walked_away / max_rounds` while `is_terminal()` checks the *stopping-rule* constants `agreement / walk_away / max_rounds` — so `is_terminal("agreed")` was `False`. "Survived" really means "reached any terminal state," so it's now `status != "active"`. Result: 5/5, all gates pass.

**Frontend/backend contract mismatch — `offer` vs `offers`.** `to_public_dict()` returns `offers` (plural), but the convergence chart and the live-arena stats read `session.offer` (singular). The markers, the gap band, and the bid/ask readouts would have silently rendered blank. Caught by reading the backend contract against the frontend before trusting the UI; fixed all four call sites to `offers`. (Verified the report and eval shapes matched exactly — only this one drifted.)

**SQLite `disk I/O error` on the mounted filesystem.** The workspace is a mounted FS that doesn't support SQLite's file locking. Rather than crash, `db.py` catches it and falls back to a temp-dir database with a single warning, and `config.DB_PATH` is overridable via `DEALBENCH_DB_PATH`. Persistence was best-effort by design, so a negotiation never depends on it.

---

## What I'd do with more time

Half-open circuit-breaker recovery (probe the provider again after a cooldown instead of staying on the fallback); a websocket push so auto-play streams instead of polling; and expanding the eval's labeled transcript set beyond the current examples to tighten the macro-F1 confidence interval. None of these change the architecture — they're refinements on top of a core that's deliberately boring where it counts.
