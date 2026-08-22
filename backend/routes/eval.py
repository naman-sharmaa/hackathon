"""
routes/eval.py — run the eval harness on demand and serve the last results.

  GET /eval/run       -> run all metrics now, persist, return the latest snapshot
  GET /eval/results   -> return the stored {"latest": ..., "history": [...]}

run_eval briefly toggles global Settings (offline mode, fake keys) inside
context managers and restores them; the server is single-threaded so this is
safe, but we still guard it so a failed run can't wedge the server.
"""
from __future__ import annotations

import json
import logging
import sys

from config import EVAL_DIR

logger = logging.getLogger("dealbench.routes.eval")

_RESULTS_FILE = EVAL_DIR / "eval_results.json"


def _load_run_eval():
    if str(EVAL_DIR) not in sys.path:
        sys.path.insert(0, str(EVAL_DIR))
    import run_eval  # noqa: E402  (eval dir isn't a package; import by name)
    return run_eval


def eval_run(params, body, query):
    try:
        mod = _load_run_eval()
        latest = mod.run_all()
        where = mod._write_results(latest)
        latest["_written_to"] = where
        return 200, latest
    except Exception as e:  # pragma: no cover - defensive
        logger.exception("eval run failed")
        return 500, {"error": f"eval run failed: {e}"}


def eval_results(params, body, query):
    if not _RESULTS_FILE.exists():
        return 200, {"latest": None, "history": [],
                     "note": "no eval has been run yet; call /eval/run"}
    try:
        return 200, json.loads(_RESULTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return 500, {"error": f"could not read results: {e}"}
