# DealBench

**Two AI agents negotiate a deal. A deterministic engine does all the math; the models only ever narrate. Either side can be taken over by a human mid-negotiation and handed back to the AI without breaking the transcript — and every single message, AI or human, is validated for price-consistency and reservation-price leaks.**

DealBench is a negotiation testbed: a buyer and a seller haggle over a price in natural language, but no number a model emits is ever trusted. The offers, the accept/reject/walk-away decisions, and the final price are computed in plain Python from each side's private reservation price. The language models are given the number the engine already decided on and asked only to say it persuasively. That separation is the whole point — it makes the negotiation *measurable*, *reproducible*, and *safe to hand to a human halfway through*.

---

## Why it's built this way

A pure "let two LLMs negotiate" demo has three problems a judge will find in thirty seconds: the models drift off the numbers they quoted, they blurt out their secret walk-away price, and the run isn't reproducible. DealBench closes all three:

- **The engine owns the math.** A closed-form concession curve produces each next offer; stopping rules decide agreement / walk-away / deadline. The model receives that number and must include it. Price-consistency is then true *by construction*, not by luck.
- **A validator guards every message.** Before any message enters the transcript — whether an AI wrote it or a human typed it during a takeover — it's checked that the stated price matches the engine's number and that it doesn't leak the side's reservation price. Leaks are flagged loudly; human price overrides are reported, not silently swallowed.
- **Everything is deterministic and runs offline.** With no API key at all, a built-in mock narrator embeds the engine's number and the entire system — negotiation, validator, classifier, eval — runs and passes. An API key only makes the prose nicer.

---

## Quickstart (zero install, no API key)

DealBench runs on the **Python 3.10+ standard library alone**. No `pip install`, no `npm`, no build step.

```bash
cd dealbench/backend
python3 app.py
# → DealBench serving on http://127.0.0.1:8000
```

Open **http://127.0.0.1:8000** in a browser. You land on the **Cornerstone Homes** marketplace: browse the listings, open a home, set your private budget ceiling and **engage your buyer agent**. The negotiation then auto-plays turn-by-turn with a live reveal; your agent **pauses for your approval** before it closes or when the contractor pushes hard. At any point you can **take over as the buyer** and type your own counter, then hand control back to the agent. When the deal closes (or someone walks), the **deal report** breaks down the ZOPA, the surplus split, tactics used, and a clean/leak integrity check.

A status pill in the top bar shows whether chat is streaming from the **live API** or the **offline narrator**, and each message is tagged with the backend that produced it (`live` / `local` / `offline`) — so you can always tell real API output from a fallback.

Run the tests and the benchmark, also with zero install:

```bash
python3 run_tests.py          # 55 unit tests
python3 eval/run_eval.py      # the five-metric benchmark; exits non-zero if a gate fails
```

## Live LLM mode (optional)

To have real models narrate instead of the mock:

```bash
cd dealbench/backend
cp .env.example .env          # then edit .env
```

Put a key for your gateway in `OPENROUTER_API_KEY` and set `OPENROUTER_BASE_URL` to that gateway's OpenAI-compatible endpoint. This works with **any OpenAI-compatible gateway** — [OpenRouter](https://openrouter.ai/keys) (`https://openrouter.ai/api/v1`), [OpenCode Zen](https://opencode.ai) (`https://opencode.ai/zen/v1`), Together, a local vLLM, etc. Pick **two different-family** models for buyer and seller, then restart `app.py`. **No `pip install` is needed** — `config.py` reads `.env` on its own (it uses `python-dotenv` if present, and otherwise parses `.env` with the standard library, so a configured key is never silently ignored). If the gateway fails mid-run, the system degrades to Ollama (if configured) and then to the mock narrator automatically — the negotiation never dies.

> Free-model IDs rotate and get delisted with little notice. Confirm your exact IDs against the gateway's live catalog with `python3 check_llm.py --list-models` (see below) before a demo.

**Verify the API is actually live** before a demo — this is the fast way to know whether chat will stream real model output or silently fall back to the offline narrator:

```bash
cd dealbench/backend
python3 check_llm.py               # probe buyer, seller & classifier
python3 check_llm.py --list-models # list the gateway's real model IDs
```

It reads `.env` exactly the way the server does (no install step), pings the buyer, seller **and** classifier models with one tiny request each, and prints a per-model ✓/✗ with the *real* error if one fails (bad key, unknown model ID, out of credit, blocked network). Exit code `0` means both buyer and seller answered (chat will be live); non-zero means at least one side will fall back. If a probe fails, it automatically cross-checks your configured IDs against the gateway's catalog and flags any that don't exist — so a typo'd or delisted model name is caught immediately. Use `--list-models` to print the full catalog and copy exact IDs into `.env`. The same check is exposed over HTTP for the UI's status pill: `GET /health/llm` returns a zero-cost config snapshot, and `GET /health/llm?probe=1` runs the live probe and returns a `live` / `partial` / `mock` verdict.

> The frontend loads React + htm from the [esm.sh](https://esm.sh) CDN (no bundler). That is the **only** network dependency of the UI; the backend has none.

---

## How a turn actually flows

```
        ┌──────────────────────── one call to advance a turn ────────────────────────┐
        │                                                                             │
  side's turn ──► engine.next_offer(reservation, counter-offer, tactic, deadline)     │
        │                    │ deterministic number N                                 │
        │                    ▼                                                         │
        │      ┌─ AI mode:  agent.narrate(N)  ──► OpenRouter ─(fail)─► Ollama ─(fail)─► mock
        │      │                                   guarantees N appears in the text    │
        │      └─ human mode: human types text; the price nearest N becomes canonical  │
        │                    │                                                         │
        │                    ▼                                                         │
        │      classifier.classify(text)   → tactic label (rules ⊕ LLM ensemble)      │
        │      validator.validate(text)    → price_ok? reservation leaked?             │
        │                    │                                                         │
        │                    ▼                                                         │
        │      offer[side] = N ;  stopping_rules.check() → agreed / walk / deadline    │
        └─────────────────────────────────────────────────────────────────────────────┘
```

The human-override rule: if you type a number while controlling a side, the number **closest to the engine's suggestion** becomes that side's canonical offer, and the engine recomputes from there next round. If you type no number, the engine's number stands. Either way the validator still runs on your words. (Rationale in [`failure_log.md`](failure_log.md).)

---

## Architecture

```
dealbench/
├── backend/                    Python stdlib only
│   ├── app.py                  http.server API + static host for the SPA
│   ├── config.py               single source of truth: tactics, engine constants, env
│   ├── catalog.py              the property listings (public fields; floor_price kept private)
│   ├── check_llm.py            standalone "is the live API working for buyer & seller?" check
│   ├── engine/                 THE DETERMINISTIC CORE (no LLM anywhere in here)
│   │   ├── concession_engine.py   closed-form diminishing-concession offer curve
│   │   ├── stopping_rules.py      agreement / walk-away / deadline / max-rounds
│   │   ├── validator.py           price-consistency + reservation-leak detection
│   │   └── tactic_classifier.py   high-precision regex rules ⊕ LLM ensemble
│   ├── agents/                 NARRATION ONLY
│   │   ├── llm_client.py          OpenRouter+Ollama via urllib; retries, backoff, breaker
│   │   ├── buyer_agent.py / seller_agent.py
│   │   └── fallback_agent.py      deterministic mock narrator (embeds the engine number)
│   ├── control/                orchestration
│   │   ├── session_state.py       per-session state + advance_turn()
│   │   ├── intervention.py        take-over / return-to-AI
│   │   └── context_builder.py     builds each side's view of the transcript
│   ├── grader/                 post-hoc analysis (no LLM)
│   │   ├── optimal_calc.py        ZOPA, surplus split, money left on the table
│   │   └── report_card.py         the end-of-deal report
│   ├── routes/                 one module per endpoint group
│   ├── db/                     sqlite3 persistence (best-effort; never fatal)
│   ├── eval/                   the benchmark harness + its datasets
│   └── tests/                  55 stdlib tests (run_tests.py, no pytest needed)
└── frontend/
    └── index.html              single-file React (CDN + htm, no build step)
```

**Design rule enforced throughout:** nothing in `engine/`, `grader/`, or the validator imports an LLM. If you delete `agents/`, the math, the validation, the stopping rules, and the eval all still run. The models are a presentation layer.

---

## API

| Method & path | Purpose |
|---|---|
| `GET /properties` · `GET /properties/{id}` | The contractor's public catalog (listings). The private `floor_price` is stripped and never sent to a client. |
| `POST /session` | Create a negotiation. Bind it to a listing with `property_id` (the seller's floor/ask come from the catalog), or pass explicit `buyer.reservation_price` / `seller.reservation_price`. Also accepts `buyer_control` (`"autopilot"` \| `"manual"`), `budget_cap`, `title`, `currency`, `deadline_round`, `max_rounds`, `tolerance`. Returns the public session state. |
| `GET /session/{id}` | Current public state (offers, mode, transcript, status). |
| `POST /session/{id}/message` | Advance one turn. Body: `{"message": "..."}` when a side is human-controlled; `{"run_to_end": true}` to auto-play remaining AI turns. If an autopilot move needs sign-off, returns `awaiting_approval` and does not advance. |
| `POST /session/{id}/approve` | Resolve a pending approval: `{"decision":"approve"}`, `{"decision":"counter","message":"..."}`, or `{"decision":"walk"}`. |
| `POST /session/{id}/intervene` | `{"side":"buyer","action":"take_over"}` or `"return_to_ai"`. |
| `GET /session/{id}/report` | End-of-deal report card. |
| `GET /eval/run` | Run the benchmark now and return the results. |
| `GET /eval/results` | Last benchmark snapshot. |
| `GET /health` · `GET /health/llm[?probe=1]` | Liveness probe; and the LLM connectivity check behind the UI's live/mock badge (`?probe=1` pings the models). |

The public state never exposes either reservation price — the UI only ever knows the *public* offers, which is why the convergence chart is honest by construction.

---

## The benchmark

`python3 eval/run_eval.py` scores five things the spec asks a judge to see and prints pass/fail gates. Latest offline run:

| Metric | Result | Gate |
|---|---|---|
| **Tactic classification** (ablation) | rules `acc 0.708 / F1 0.696` · LLM `0.708 / 0.641` · **ensemble `0.750 / 0.656`** | ensemble ≥ both ✓ |
| **Price consistency** across full negotiations | 100% (78/78 agent messages quote the engine number) | ≥ 99% ✓ |
| **Reservation-leak detection** | recall 100%, false-positive 0% | no miss / no false-positive ✓ |
| **Stopping-rule accuracy** | 100% (10/10 scripted scenarios) | perfect ✓ |
| **Fallback-trigger success** | 100% (5/5 simulated API failures survived) | all survive ✓ |

The headline is the **ablation**: the hybrid ensemble (high-precision regex rules deferring to an LLM/heuristic on the rest) beats either component alone, which is exactly the argument for the hybrid design. The eval runs fully offline, so these numbers are reproducible on any machine with no key.

---

## Testing

```bash
cd dealbench/backend
python3 run_tests.py
```

55 tests, no third-party test runner. They cover the concession curve and the guarantee that **offers never cross reservation prices**, the stopping rules, the validator (including a human-takeover leak being caught), the classifier ensemble, the grader math, and a full auto-negotiation reaching agreement plus a clean take-over → return-to-AI cycle.

## Notes for running in constrained sandboxes

SQLite needs a filesystem that supports file locking. On some mounted/networked filesystems that fails; DealBench treats persistence as best-effort and automatically falls back to a temp-dir database (you'll see one `WARNING` line and everything keeps working). To point it at local disk explicitly, set `DEALBENCH_DB_PATH=/path/on/local/disk/dealbench.db`.

See [`failure_log.md`](failure_log.md) for the decisions behind the stdlib-only stance, the CDN frontend, the human-override policy, and the fallback ladder.
