# DealBench - Project Documentation

# Github Link
https://github.com/naman-sharmaa/hackathon

## 1. What We Built and How It Works

**DealBench** is an advanced AI negotiation testbed where two AI agents (a buyer and a seller) haggle over a price in natural language. 

The core philosophy of DealBench is that **language models are great narrators but terrible calculators**. A pure "let two LLMs negotiate" demo usually fails because models drift off their quoted numbers, accidentally blurt out their secret walk-away prices, and produce non-reproducible runs.

### How It Works
DealBench solves these issues by completely separating the *math* from the *narration*:
1. **The Engine Owns the Math:** A deterministic, closed-form concession curve computes each side's next offer based on their private reservation price, round number, and counter-tactic. Stopping rules explicitly decide when they reach an agreement, walk away, or hit a deadline.
2. **Models Only Narrate:** The LLM is handed the exact number it needs to pitch and is tasked purely with persuading the other side.
3. **Strict Validation:** Before any message enters the transcript, it passes through a validator that checks for exact price consistency and ensures no reservation prices are leaked.
4. **Human-in-the-Loop:** A human can take over either side mid-negotiation, type a custom counter-offer, and hand it back to the AI without breaking the session state.

Everything runs seamlessly with **zero dependencies**—the backend relies strictly on the Python 3.10+ standard library, and the frontend is a no-build React application delivered via CDN.

---

## 2. Team Members & Contributions

Our team collaborated closely across Full Stack and AI/ML boundaries to bring this highly reliable architecture to life.

* **Naman Sharma (Full Stack)**
  * **Architecture & Orchestration:** Architected the zero-dependency Python backend utilizing `http.server`. 
  * **Frontend Development:** Built the complete no-build React SPA using HTM and CDN imports, ensuring a clean, responsive UI with real-time transcript tracking and intervention controls.
  * **Session Management:** Engineered the orchestration layer (`session_state.py`) that manages the conversational turn-taking, human-in-the-loop takeovers, and manual approval gates.

* **Piyush Rawat (AI/ML)**
  * **Tactic Classifier Ensemble:** Designed and implemented the hybrid tactic classifier that uses high-precision regex rules augmented by an LLM ensemble to reliably detect negotiation tactics (e.g., walk-away threats, deadlines).
  * **Resilient Agent Pipeline:** Built the LLM client infrastructure with circuit breakers. Integrated OpenRouter with graceful fallbacks to Ollama and finally to a deterministic mock narrator to guarantee the system never crashes during a live demo.

* **Deepak Kumar (Full Stack)**
  * **Deterministic Math Engine:** Developed the closed-form diminishing-concession offer curves and the complex stopping rules (agreement on crossover, maximum rounds, walk-aways).
  * **Grader & Analytics:** Built the post-hoc analysis tools (`optimal_calc.py` and `report_card.py`) to calculate ZOPA (Zone of Possible Agreement), surplus splits, and money left on the table.
  * **Persistence Layer:** Integrated best-effort SQLite persistence ensuring negotiations can be saved and retrieved without requiring external database setups.

* **Anmol Kannaujiya (AI/ML)**
  * **Strict Validation System:** Engineered the rigorous validator (`validator.py`) responsible for ensuring absolute price consistency and detecting inadvertent reservation-price leaks.
  * **Evaluation Harness:** Built the fully offline evaluation benchmark suite (`run_eval.py`) that scores the system on 5 key metrics (tactic accuracy, consistency, leak detection, stopping rules, and fallbacks).
  * **Prompt Engineering:** Refined the system prompts for the Buyer and Seller agents to ensure highly persuasive, context-aware narrations while strictly adhering to the engine's numerical constraints.

---

## 3. Key Features

* **Engine-Driven Negotiation:** LLMs are stripped of their numerical autonomy, making the negotiation mathematically measurable, reproducible, and safe.
* **Seamless Human Intervention:** Humans can set soft budget caps that pause the AI for approval. A human can also "Take Over" to send a custom message, which the engine intelligently reads, extracting the human's price to compute the next round.
* **Hybrid Tactic Classification:** A combination of fast, hardcoded rules and LLM validation allows the engine to adapt dynamically to aggressive tactics like extreme deadlines.
* **Zero-Install Philosophy:** The backend runs without `pip install` (no external web frameworks), and the frontend requires no `npm` or Webpack.
* **Comprehensive Grader:** Every completed negotiation generates a detailed report card evaluating value capture, surplus splits, and overall session integrity.

---

## 4. Technical Decisions & Challenges

### Technical Decisions
* **Python Standard Library Only:** We deliberately chose not to use frameworks like FastAPI or Flask. By using `http.server`, we ensured that any judge or user could clone the repo and run it instantly (`python app.py`) in highly constrained sandbox environments.
* **No-Build React Frontend:** To maintain the zero-install philosophy, we utilized React + HTM via jsDelivr CDN. This gives us the component-driven power of React without the overhead of Node.js or a bundler.
* **Mock Narrator Fallback:** We decided the negotiation must *never* die. If API keys exhaust or rate limits hit, the system elegantly downgrades to local models, and finally to a deterministic text generator, ensuring the demo always completes.

### Challenges Conquered
* **LLM Hallucination and Drifting:** Early on, agents would agree to prices outside their budget or leak their walk-away prices. *Solution:* We built the strict separation of concerns where the Python Engine does the math, and the Validator intercepts and filters rogue LLM outputs.
* **Human-to-AI Handoff:** Allowing a human to inject custom text and hand control back to the AI risked breaking the mathematical curve. *Solution:* We implemented an extraction algorithm that parses the human's text for numerical offers. The engine then treats the closest valid number as the new canonical anchor and recomputes the concession curve seamlessly for the next round.
* **Tactic Identification Speed vs. Accuracy:** Relying purely on LLMs to classify opponent tactics was too slow and occasionally inaccurate. *Solution:* We implemented an ablation-tested hybrid ensemble where fast regex rules handle clear cases (e.g., "final offer"), deferring to the LLM only for ambiguous text.
