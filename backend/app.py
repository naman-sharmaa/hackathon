"""
app.py — DealBench HTTP server (Python standard library only).

No FastAPI, no uvicorn, no third-party anything: just http.server. This is a
deliberate design choice (see failure_log.md) — the sandbox has no package
network, and "clone + `python app.py`" with zero install is a real virtue for a
hackathon judge. The trade-offs (single-threaded, hand-rolled routing) are fine
at demo scale.

Endpoints (spec Section 8):
    POST /session                  create a negotiation
    GET  /session/{id}             current public state
    POST /session/{id}/message     advance one turn (+ optional human message)
    POST /session/{id}/intervene   take over / return control
    GET  /session/{id}/report      end-of-deal report card
    GET  /eval/run                 run the eval harness now
    GET  /eval/results             last eval snapshot
    GET  /health                   liveness probe
    GET  /*                        the single-page frontend (SPA fallback)

Run:  python app.py            (defaults to 127.0.0.1:8000)
      PORT=9000 python app.py
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Make the backend package importable when launched directly.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import FRONTEND_DIR  # noqa: E402
from routes import session as r_session  # noqa: E402
from routes import intervene as r_intervene  # noqa: E402
from routes import report as r_report  # noqa: E402
from routes import eval as r_eval  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("dealbench.app")

# --- best-effort DB init (never fatal) --------------------------------------
try:
    from db import db
    db.init_db()
    logger.info("DB ready at %s", db.db_path())
except Exception as e:  # pragma: no cover
    logger.warning("DB unavailable, continuing without persistence: %s", e)


# ---------------------------------------------------------------------------
# Route table:  (METHOD, compiled_path_regex, handler)
# handler(params: dict, body: dict, query: dict) -> (status_int, payload_dict)
# ---------------------------------------------------------------------------
def _rx(pattern: str) -> re.Pattern:
    return re.compile("^" + pattern + "$")


ROUTES = [
    ("POST", _rx(r"/session"), r_session.create_session),
    ("GET", _rx(r"/session/(?P<id>[^/]+)"), r_session.get_session),
    ("POST", _rx(r"/session/(?P<id>[^/]+)/message"), r_session.post_message),
    ("POST", _rx(r"/session/(?P<id>[^/]+)/intervene"), r_intervene.intervene),
    ("GET", _rx(r"/session/(?P<id>[^/]+)/report"), r_report.report),
    ("GET", _rx(r"/eval/run"), r_eval.eval_run),
    ("GET", _rx(r"/eval/results"), r_eval.eval_results),
    ("GET", _rx(r"/health"), lambda p, b, q: (200, {"ok": True, "service": "dealbench"})),
]

_API_PREFIXES = ("/session", "/eval", "/health")


class DealBenchHandler(BaseHTTPRequestHandler):
    server_version = "DealBench/1.0"

    # -- plumbing ----------------------------------------------------------
    def log_message(self, fmt, *args):  # keep the console readable
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, payload: dict, content_type="application/json"):
        body = json.dumps(payload).encode("utf-8") if content_type == "application/json" else payload
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _read_body(self) -> tuple[dict | None, str | None]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}, None
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}, None
        try:
            obj = json.loads(raw.decode("utf-8"))
            if not isinstance(obj, dict):
                return None, "JSON body must be an object"
            return obj, None
        except json.JSONDecodeError as e:
            return None, f"invalid JSON: {e}"

    # -- verbs -------------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_HEAD(self):
        self._dispatch("GET")

    # -- core dispatch -----------------------------------------------------
    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}

        matched_path = False
        for m, rx, handler in ROUTES:
            match = rx.match(path)
            if not match:
                continue
            matched_path = True
            if m != method:
                continue
            body, err = ({}, None) if method == "GET" else self._read_body()
            if err:
                return self._send(400, {"error": err})
            try:
                status, payload = handler(match.groupdict(), body, query)
            except Exception as e:  # pragma: no cover - last-resort guard
                logger.exception("handler error on %s %s", method, path)
                return self._send(500, {"error": f"internal error: {e}"})
            return self._send(status, payload)

        # No API route matched.
        if matched_path:
            return self._send(405, {"error": f"method {method} not allowed on {path}"})
        if method == "GET" and not path.startswith(_API_PREFIXES):
            return self._serve_static(path)
        return self._send(404, {"error": f"no route for {method} {path}"})

    # -- static / SPA ------------------------------------------------------
    def _serve_static(self, path: str):
        root = Path(FRONTEND_DIR)
        index = root / "index.html"
        rel = path.lstrip("/")
        candidate = (root / rel).resolve()

        # Serve a real asset if it exists and is safely under the frontend dir.
        if rel and root in candidate.parents and candidate.is_file():
            ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
            return self._send(200, candidate.read_bytes(), content_type=ctype)

        # SPA fallback -> index.html (client-side routing).
        if index.is_file():
            return self._send(200, index.read_bytes(), content_type="text/html; charset=utf-8")

        # Frontend not built yet — helpful placeholder so the API is still usable.
        return self._send(200, _PLACEHOLDER_HTML, content_type="text/html; charset=utf-8")


_PLACEHOLDER_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>DealBench</title><style>body{font:16px/1.5 system-ui;margin:3rem auto;max-width:40rem;color:#222}
code{background:#f4f4f5;padding:.15rem .4rem;border-radius:4px}</style></head>
<body><h1>DealBench API is running</h1>
<p>The frontend hasn't been added yet. The API is live — try:</p>
<ul><li><code>GET /health</code></li><li><code>GET /eval/results</code></li>
<li><code>POST /session</code> then <code>POST /session/{id}/message</code></li></ul>
</body></html>"""


def main() -> int:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), DealBenchHandler)
    logger.info("DealBench serving on http://%s:%d  (frontend dir: %s)", host, port, FRONTEND_DIR)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
