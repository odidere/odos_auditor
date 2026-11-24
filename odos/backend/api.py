"""HTTP API.

Run with ``odos api`` (or ``uvicorn odos.backend.api:app``). If ``ODOS_API_KEY``
is set, every request except ``/healthz`` must send it in ``X-API-Key``.
"""
from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from odos.backend.cost_engine import CostEngine, event_to_dict, suggestion_to_dict
from odos.backend.db import get_engine, init_db, session_factory
from odos.backend.models import AuditEvent, Suggestion
from odos.backend.remediation import ReviewError, acceptance_rate, approve, generate_suggestions, reject
from odos.backend.service import EnterpriseAuditor
from odos.backend.surgeon import Surgeon
from odos.sources import build_source

logger = logging.getLogger("odos.api")


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("ODOS_API_KEY")
    if expected and not (x_api_key and hmac.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


class Review(BaseModel):
    reviewer: str
    note: str | None = None


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="Odos Auditor API", version="0.2.0",
                  description="Warehouse cost anomaly detection with human-reviewed AI suggestions.")
    auth = [Depends(require_api_key)]

    @app.get("/healthz", tags=["Ops"])
    def healthz():
        return {"status": "ok"}

    @app.post("/api/v1/audit/run", tags=["Auditor"], dependencies=auth)
    def trigger_audit(lookback_days: int = Query(1, ge=1, le=30), source: str | None = None,
                      suggest: bool = False, db: Session = Depends(get_db)):
        try:
            cost_source = build_source(source)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            report = EnterpriseAuditor(db, cost_source).run_audit_cycle(lookback=lookback_days)
            if suggest:
                report["suggestions"] = [suggestion_to_dict(s) for s in generate_suggestions(db, Surgeon())]
        except Exception:
            logger.exception("Audit cycle failed")
            raise HTTPException(status_code=500, detail="Audit cycle failed; see server logs")
        return {"status": "success", "source": cost_source.name,
                "timestamp": datetime.now(timezone.utc).isoformat(), "report": report}

    @app.get("/api/v1/audit/events", tags=["Reports"], dependencies=auth)
    def audit_events(limit: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)):
        rows = db.scalars(select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(limit)).all()
        return [event_to_dict(e) for e in rows]

    # Old path kept for compatibility.
    app.get("/api/v1/audit/history", tags=["Reports"], dependencies=auth)(audit_events)

    @app.get("/api/v1/summary", tags=["Reports"], dependencies=auth)
    def summary():
        return CostEngine(get_engine()).get_financial_summary()

    @app.get("/api/v1/suggestions", tags=["Suggestions"], dependencies=auth)
    def list_suggestions(status: str | None = Query(None, pattern="^(PENDING|INVALID|FAILED|APPROVED|REJECTED)$"),
                         limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
        stmt = select(Suggestion).order_by(Suggestion.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(Suggestion.status == status)
        return [suggestion_to_dict(s) for s in db.scalars(stmt).all()]

    @app.post("/api/v1/suggestions/{suggestion_id}/approve", tags=["Suggestions"], dependencies=auth)
    def approve_suggestion(suggestion_id: int, review: Review, db: Session = Depends(get_db)):
        try:
            return suggestion_to_dict(approve(db, suggestion_id, review.reviewer, review.note))
        except ReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/v1/suggestions/{suggestion_id}/reject", tags=["Suggestions"], dependencies=auth)
    def reject_suggestion(suggestion_id: int, review: Review, db: Session = Depends(get_db)):
        try:
            return suggestion_to_dict(reject(db, suggestion_id, review.reviewer, review.note))
        except ReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/api/v1/suggestions/acceptance", tags=["Suggestions"], dependencies=auth)
    def suggestion_acceptance(db: Session = Depends(get_db)):
        return acceptance_rate(db)

    @app.get("/api/v1/infra/advisor", tags=["Infrastructure"], dependencies=auth)
    def infrastructure_advice(lookback_days: int = Query(7, ge=1, le=30), source: str | None = None):
        from odos.backend.advisor import WarehouseAdvisor
        from odos.config import section

        cost_source = build_source(source)
        if not hasattr(cost_source, "fetch_warehouse_usage"):
            return []
        usage = cost_source.fetch_warehouse_usage(lookback_days)
        return WarehouseAdvisor(usage, float(section("costs").get("compute_credit_price", 3.0)),
                                section("advisor")).recommendations()

    return app


app = create_app()
