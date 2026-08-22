"""
routes/report.py — the end-of-negotiation report card.

  GET /session/{id}/report   -> grader.report_card.build_report(session)
"""
from __future__ import annotations

from grader.report_card import build_report
from routes import store


def report(params, body, query):
    session = store.get(params["id"])
    if session is None:
        return 404, {"error": "session not found"}
    return 200, build_report(session)
