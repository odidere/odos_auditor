"""From anomaly to reviewed suggestion.

1. :func:`generate_suggestions` asks the Surgeon for a rewrite of each new
   HIGH/CRITICAL anomaly (one open suggestion per query fingerprint, capped
   per cycle) and stores it as PENDING, INVALID or FAILED.
2. A person calls :func:`approve` or :func:`reject`. Approving records the
   decision only; applying the change is up to the engineer.
3. Every decision is appended to a JSON Lines file, which doubles as an
   evaluation dataset: how often were the model's suggestions accepted?
"""
from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from odos.backend.models import AuditEvent, QueryFingerprint, Suggestion, utcnow
from odos.config import section

OPEN_STATUSES = ("PENDING",)
REVIEWABLE = ("PENDING",)


class ReviewError(ValueError):
    pass


def generate_suggestions(db: Session, surgeon: Any, limit: int | None = None,
                         severities: tuple[str, ...] = ("HIGH", "CRITICAL")) -> list[Suggestion]:
    limit = limit if limit is not None else int(section("ai").get("max_suggestions_per_cycle", 10))
    if limit <= 0 or not getattr(surgeon, "available", True):
        return []
    has_suggestion = select(Suggestion.id).where(Suggestion.audit_event_id == AuditEvent.id).exists()
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.severity.in_(severities), ~has_suggestion)
        .order_by(AuditEvent.waste_usd.desc())
    ).all()

    created: list[Suggestion] = []
    seen: set[str] = set()
    for event in events:
        if len(created) >= limit:
            break
        if event.fingerprint_id in seen:
            continue
        open_exists = db.scalar(select(Suggestion.id).where(
            Suggestion.fingerprint_id == event.fingerprint_id, Suggestion.status.in_(OPEN_STATUSES)))
        fp = db.get(QueryFingerprint, event.fingerprint_id)
        if open_exists or fp is None or not fp.sql_sample:
            continue
        seen.add(event.fingerprint_id)
        result = surgeon.optimize_sql(
            fp.sql_sample, task_id=event.task_id or event.fingerprint_id,
            cost_usd=event.cost_usd or 0.0, baseline_usd=event.baseline_usd or 0.0,
            already_redacted=not bool(section("ai").get("send_literals", False)),
        )
        suggestion = Suggestion(
            audit_event_id=event.id, fingerprint_id=event.fingerprint_id,
            original_sql=result.sent_sql, suggested_sql=result.suggested_sql,
            diagnosis=result.diagnosis, strategy=result.strategy,
            estimated_savings_pct=result.estimated_savings_pct,
            provider=result.provider, model=result.model, latency_ms=result.latency_ms,
            status="PENDING" if result.status == "VALID" else result.status,
            validation_notes="\n".join(result.notes) or None,
        )
        db.add(suggestion)
        created.append(suggestion)
    db.commit()
    return created


def _decide(db: Session, suggestion_id: int, status: str, reviewer: str, note: str | None) -> Suggestion:
    suggestion = db.get(Suggestion, suggestion_id)
    if suggestion is None:
        raise ReviewError(f"Suggestion {suggestion_id} not found")
    if suggestion.status not in REVIEWABLE:
        raise ReviewError(f"Suggestion {suggestion_id} is {suggestion.status}; only PENDING suggestions can be reviewed")
    if not reviewer:
        raise ReviewError("A reviewer name is required")
    suggestion.status = status
    suggestion.decided_by = reviewer
    suggestion.decided_at = utcnow()
    suggestion.decision_note = note
    db.commit()
    record_decision(suggestion)
    return suggestion


def approve(db: Session, suggestion_id: int, reviewer: str, note: str | None = None) -> Suggestion:
    """Mark a suggestion as approved. Nothing is executed."""
    return _decide(db, suggestion_id, "APPROVED", reviewer, note)


def reject(db: Session, suggestion_id: int, reviewer: str, note: str | None = None) -> Suggestion:
    return _decide(db, suggestion_id, "REJECTED", reviewer, note)


def record_decision(suggestion: Suggestion, path: str | None = None) -> None:
    path = path or os.getenv("ODOS_DECISIONS_PATH", "odos_decisions.jsonl")
    entry = {
        "suggestion_id": suggestion.id, "fingerprint": suggestion.fingerprint_id,
        "decision": suggestion.status, "reviewer": suggestion.decided_by, "note": suggestion.decision_note,
        "provider": suggestion.provider, "model": suggestion.model, "strategy": suggestion.strategy,
        "estimated_savings_pct": suggestion.estimated_savings_pct,
        "input_sql": suggestion.original_sql, "output_sql": suggestion.suggested_sql,
        "decided_at": suggestion.decided_at.isoformat() if suggestion.decided_at else None,
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def acceptance_rate(db: Session) -> dict[str, Any]:
    """Share of reviewed suggestions that were approved, per model."""
    rows = db.execute(select(Suggestion.model, Suggestion.status)
                      .where(Suggestion.status.in_(("APPROVED", "REJECTED")))).all()
    stats: dict[str, dict[str, int]] = {}
    for model, status in rows:
        s = stats.setdefault(model or "unknown", {"approved": 0, "rejected": 0})
        s["approved" if status == "APPROVED" else "rejected"] += 1
    return {m: {**s, "rate": s["approved"] / (s["approved"] + s["rejected"])} for m, s in stats.items()}
