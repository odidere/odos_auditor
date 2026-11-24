"""Offline evaluation of the Surgeon on known-expensive query patterns.

Each case in ``eval/cases.jsonl`` has an ``id``, ``sql`` and ``expect_any``:
keywords of which at least one should appear in the model's strategy or
diagnosis. A case passes when the response is valid JSON, the rewrite passes
validation (one read-only statement, same tables) and a keyword matches.

This needs a real provider (OPENAI_API_KEY or GEMINI_API_KEY); it costs a few
cents per run. Run it with ``odos eval``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CASES = Path(__file__).resolve().parent.parent / "eval" / "cases.jsonl"


def load_cases(path: str | Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def score_case(case: dict[str, Any], result: Any) -> dict[str, Any]:
    text = f"{result.strategy or ''} {result.diagnosis or ''}".lower()
    keyword_hit = any(k.lower() in text for k in case.get("expect_any", []))
    answered = result.status != "FAILED"
    valid = result.status == "VALID"
    return {
        "id": case["id"],
        "answered": answered,
        "valid_sql": valid,
        "keyword_match": keyword_hit,
        "passed": answered and valid and keyword_hit,
        "strategy": result.strategy,
        "notes": result.notes,
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
    }


def run_eval(surgeon: Any, cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cases = cases if cases is not None else load_cases()
    scored = [score_case(c, surgeon.optimize_sql(c["sql"], task_id=c["id"])) for c in cases]
    total = len(scored) or 1
    return {
        "cases": len(scored),
        "pass_rate": sum(s["passed"] for s in scored) / total,
        "valid_sql_rate": sum(s["valid_sql"] for s in scored) / total,
        "keyword_rate": sum(s["keyword_match"] for s in scored) / total,
        "results": scored,
    }
