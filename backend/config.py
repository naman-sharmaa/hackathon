"""
Central configuration for DealBench.

Everything tunable lives here so the deterministic engine, agents, validator,
classifier, and eval harness all agree on the same constants.  Env vars are
loaded from `.env` (see `.env.example`); sensible defaults keep the whole
system runnable with *no* API key at all (offline mock-narrator mode).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Load backend/.env regardless of where the process is launched from.
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(int(default))).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Tactic taxonomy — the SINGLE source of truth.
#
# The rules classifier, the LLM classifier prompt, the eval label set, and the
# report card all import from here so nothing drifts out of sync.  Eval
# transcripts may use compound labels ("comparables+walk_away_threat"); split
# on '+' to compare against this canonical set.
# ---------------------------------------------------------------------------
TACTICS: tuple[str, ...] = (
    "anchoring",            # opening far from the target to set the frame
    "walk_away_threat",     # signalling willingness to leave
    "comparables",          # citing other listings / market rates as leverage
    "silence",              # stalling, non-committal, "let me think"
    "splitting_difference", # "let's meet in the middle"
    "deadline_pressure",    # invoking a time limit to force a decision
    "concession",           # explicitly moving toward the counterparty
    "flattery",             # relationship-building / softening
    "neutral",              # informational, no discernible tactic
)

# Human-readable descriptions — fed to the LLM classifier prompt and shown in
# the report card so a judge understands each label.
TACTIC_DESCRIPTIONS: dict[str, str] = {
    "anchoring": "Opens or holds a price far from the counterparty to anchor the range.",
    "walk_away_threat": "Signals willingness to leave the deal to extract movement.",
    "comparables": "Cites other listings, market rates, or comps as leverage.",
    "silence": "Stalls, deflects, or stays non-committal instead of countering.",
    "splitting_difference": "Proposes meeting in the middle of the current gap.",
    "deadline_pressure": "Invokes a time limit or expiry to force a decision.",
    "concession": "Explicitly moves price toward the counterparty.",
    "flattery": "Builds rapport / softens tone to grease the deal.",
    "neutral": "Informational or procedural; no discernible tactic.",
}


@dataclass(frozen=True)
class EngineDefaults:
    """Defaults for the deterministic concession engine + stopping rules."""
    tolerance: float = 500.0          # |buyer-seller| <= tolerance => agreement
    max_rounds: int = 20              # hard cap; never loops forever
    walk_away_gap_ratio: float = 0.25 # gap > this * midpoint after patience => walk
    walk_away_patience: int = 6       # rounds of a too-wide gap before walking
    # Concession curve shape: step_r = base_fraction * decay**round of the
    # remaining distance to reservation.  Diminishing => feels human.
    base_concession_fraction: float = 0.35
    concession_decay: float = 0.80
    min_concession: float = 50.0      # floor so late rounds still move a little
    deadline_midpoint_pull: float = 0.5  # final-round pull toward the midpoint


@dataclass(frozen=True)
class Settings:
    # --- LLM / provider ---
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "").strip())
    openrouter_base_url: str = field(default_factory=lambda: os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    buyer_model: str = field(default_factory=lambda: os.getenv("BUYER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"))
    seller_model: str = field(default_factory=lambda: os.getenv("SELLER_MODEL", "qwen/qwen3-coder:free"))
    classifier_model: str = field(default_factory=lambda: os.getenv("CLASSIFIER_MODEL", "meta-llama/llama-3.2-3b-instruct:free"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_FALLBACK_MODEL", "llama3.2:1b"))
    ollama_host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    app_url: str = field(default_factory=lambda: os.getenv("OPENROUTER_APP_URL", ""))
    app_title: str = field(default_factory=lambda: os.getenv("OPENROUTER_APP_TITLE", "DealBench"))

    # --- resilience knobs ---
    circuit_breaker_threshold: int = field(default_factory=lambda: _int("CIRCUIT_BREAKER_THRESHOLD", 2))
    max_retries: int = field(default_factory=lambda: _int("LLM_MAX_RETRIES", 3))
    timeout_seconds: int = field(default_factory=lambda: _int("LLM_TIMEOUT_SECONDS", 30))
    offline: bool = field(default_factory=lambda: _bool("DEALBENCH_OFFLINE", False))

    engine: EngineDefaults = field(default_factory=EngineDefaults)

    @property
    def has_openrouter(self) -> bool:
        """True when a real key is configured and we're not forced offline."""
        return bool(self.openrouter_api_key) and not self.offline

    def model_for(self, side: str) -> str:
        return self.buyer_model if side == "buyer" else self.seller_model


SETTINGS = Settings()

# Paths
BACKEND_DIR = Path(__file__).resolve().parent
EVAL_DIR = BACKEND_DIR / "eval"
# DB path may be overridden (e.g. some mounted/networked filesystems don't
# support SQLite's file locking; point this at local disk there).
DB_PATH = Path(os.getenv("DEALBENCH_DB_PATH", str(BACKEND_DIR / "db" / "dealbench.db")))
SCHEMA_PATH = BACKEND_DIR / "db" / "schema.sql"
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
