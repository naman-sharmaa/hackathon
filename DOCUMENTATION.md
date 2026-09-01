# DealBench - Deep Dive Preparation Guide

This documentation is designed to help the team prepare in-depth for project presentation and technical deep-dives. The project architecture has been divided into four specific domains. Each team member should master their assigned section to comprehensively explain how that part of the DealBench system works.

---

## 1. Evaluation & Analytics
**Assigned to: Team Member 1 (Anmol Kannaujiya / AI/ML)**
**Focus Areas:** `backend/eval/`, `backend/grader/`, `run_eval.py`

Your domain is responsible for judging how well the negotiation performed, analyzing the mathematics of the deal, and running benchmark suites to ensure system integrity.

### Key Concepts to Master:
*   **ZOPA (Zone of Possible Agreement):** Be able to explain that ZOPA is the overlap between the buyer's absolute maximum budget and the seller's absolute minimum acceptable price. If the buyer can pay up to $500k and the seller will take as low as $450k, the ZOPA is $50k.
*   **Optimal Splits (`optimal_calc.py`):** Understand how the engine computes the "perfect" mathematically fair deal. It assesses how much surplus value was created and determines if the AI agent or the human captured more of the value.
*   **Report Cards (`report_card.py`):** At the end of every negotiation (whether agreed or walked away), your module generates a detailed post-game report. It tracks the number of rounds, ZOPA width, surplus captured, and crucially, flags any "leak failures" or inconsistencies.
*   **Offline Benchmark Suite (`run_eval.py`):** DealBench features a fully offline evaluation harness. Be prepared to explain how we score the system across 5 key metrics:
    1. Tactic accuracy
    2. Pricing consistency
    3. Leak detection
    4. Stopping rules efficiency
    5. Fallback resilience.

---

## 2. Core Engine & Validation
**Assigned to: Team Member 2 (Deepak Kumar / Full Stack)**
**Focus Areas:** `backend/engine/`, `backend/engine/validator.py`, `backend/engine/stopping_rules.py`

Your domain is the beating mathematical heart of DealBench. You own the rules of the game.

### Key Concepts to Master:
*   **Separation of Math and Prose:** The foundational philosophy of DealBench. Be able to explain that Large Language Models are terrible at doing reliable math. Therefore, *your* engine computes the exact dollar amount for every turn, and the LLM is strictly used as a narrator to pitch that specific number.
*   **Concession Curves:** You manage how offers are calculated. As rounds progress, the AI's offers follow a deterministic, diminishing-return concession curve toward their private reservation price, factoring in the opponent's counter-tactics.
*   **Strict Validation (`validator.py`):** Before any AI message reaches the user, your validator intercepts it. It uses regex `extract_prices()` to guarantee the LLM included the exact assigned number. Most importantly, it ensures the LLM did **not** accidentally leak its secret walk-away price. If a small model hallucinates the wrong number, your validator catches it.
*   **Stopping Rules (`stopping_rules.py`):** The LLMs do not decide when the deal is done. Your deterministic rules do. You check every round to see if:
    *   **Agreement:** `buyer_offer >= seller_offer` (prices have crossed).
    *   **Max Rounds:** Hard cap hit without a deal.
    *   **Walk Away:** The gap remains too wide after a certain patience threshold.

---

## 3. Agents & Model Integration
**Assigned to: Team Member 3 (Piyush Rawat / AI/ML)**
**Focus Areas:** `backend/agents/`, `backend/engine/tactic_classifier.py`

Your domain involves interacting with the Large Language Models, crafting their personas, classifying their behavior, and handling API resilience.

### Key Concepts to Master:
*   **Multi-Model Strategy & API Clients (`llm_client.py`):** Be prepared to explain how we use OpenRouter to access frontier models. To guarantee authentic negotiations without model "collusion," we strictly enforce that the Buyer and Seller use different model families (e.g., Buyer = **GPT-4o-mini**, Seller = **Claude 3 Haiku**). You also manage the `diagnose` endpoints and circuit breakers that switch to a mock fallback if rate limits are hit.
*   **Agent Personas & Prompts (`base_agent.py`):** You control the system instructions. Explain how the prompts force the AI to weave the engine's exact mathematical offer into natural conversation. Discuss recent refinements, such as the strict ban on "roleplay actions" (e.g., `*smiles*`, `*pauses*`), forcing the models to output pure professional dialogue.
*   **Tactic Classification (`tactic_classifier.py`):** You analyze the opponent's text to figure out their strategy. Be ready to explain the hybrid ensemble approach:
    1.  A fast, hardcoded Regex pass checks for obvious phrases (e.g., "final offer" = `anchoring`).
    2.  An LLM classification pass (using GPT-4o-mini) handles semantic nuance.
    3.  Your ensemble logic merges them to confidently detect tactics like `walk_away_threat`, `deadline_pressure`, or `splitting_difference`.

---

## 4. Frontend, Guardrails, Backend, DB & Control Flow
**Assigned to: Team Member 4 (Naman Sharma / Full Stack)**
**Focus Areas:** `frontend/`, `backend/app.py`, `backend/routes/`, `backend/control/session_state.py`, `backend/control/guardrail.py`, `backend/db/`

Your domain is the orchestration layer. You tie the entire user experience together, managing how data flows from the browser, through the safety checks, into the state machine, and down to the database.

### Key Concepts to Master:
*   **Zero-Build Frontend (`frontend/index.html`):** Explain the decision to use a zero-dependency React SPA powered by `htm` over CDN. You manage the dynamic UI, including the live API health badge, real-time typing indicators, the deal ledger, and the seamless manual takeover controls.
*   **Conversational Guardrails (`guardrail.py`):** When a human manually intervenes, you protect the system. Be ready to explain how you route human messages through an LLM classifier to determine if they are in-scope. If a user tries to chit-chat, do math, or speak off-topic, your guardrail strictly rejects the payload with an HTTP 400 "Out of scope" error.
*   **Session State Machine (`session_state.py`):** You are the traffic cop. You manage `advance_turn()`, which dictates who speaks next. Explain how you implemented the manual intervention overrides, including the recent updates that allow a user to stay in manual mode indefinitely, and the manual cancellation hook (where detecting "cancel" or "stop" instantly forces a walk-away termination).
*   **Zero-Dependency Server & Routes (`app.py`):** Explain how DealBench eschews Flask/FastAPI in favor of Python's native `ThreadingHTTPServer`. You built a lightweight REST framework capable of handling concurrent negotiation streams effortlessly.
*   **Persistence Layer (`backend/db/`):** Be able to explain the SQLite database (`dealbench.db`) powered by `db.py`. It is used to persist session metadata, chat transcripts, final deal statuses, and report cards, ensuring that all negotiations are safely recorded for the frontend list view and post-deal analytics.
