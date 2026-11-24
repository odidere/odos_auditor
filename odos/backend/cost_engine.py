"""Read-side summaries for the API, UI and PDF report."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from odos.backend.db import get_engine
from odos.backend.models import AuditEvent, DailyCost, Suggestion, utcnow
from odos.backend.reporting import calculate_efficiency
from odos.config import section


class CostEngine:
    def __init__(self, engine: Engine | None = None):
        self.engine = engine or get_engine()
        self.budget_cap = section("app").get("budget_cap", 2000)

    def get_financial_summary(self, days: int = 30) -> dict[str, Any]:
        since = (utcnow() - timedelta(days=days)).date()
        with Session(self.engine) as s:
            total_cost, cost_days = s.execute(
                select(func.coalesce(func.sum(DailyCost.cost_usd), 0.0), func.count(func.distinct(DailyCost.day)))
                .where(DailyCost.day >= since)).one()
            total_waste = s.scalar(select(func.coalesce(func.sum(AuditEvent.waste_usd), 0.0))
                                   .where(AuditEvent.timestamp >= since)) or 0.0
        cost_days = cost_days or 0
        daily_spend = float(total_cost) / cost_days if cost_days else 0.0
        daily_waste = float(total_waste) / cost_days if cost_days else 0.0
        annual_burn, annual_waste = daily_spend * 365, daily_waste * 365
        return {
            # daily_spend includes the waste; daily_base excludes it.
            "daily_spend": daily_spend,
            "daily_base": max(0.0, daily_spend - daily_waste),
            "daily_waste": daily_waste,
            "annual_burn": annual_burn,
            "annual_waste": annual_waste,
            "efficiency_score": int(calculate_efficiency(annual_burn, annual_waste)),
            "budget_cap": self.budget_cap,
            "days_observed": cost_days,
        }

    def get_anomalies(self, limit: int = 200) -> list[dict[str, Any]]:
        with Session(self.engine) as s:
            rows = s.scalars(select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(int(limit))).all()
            return [event_to_dict(e) for e in rows]

    def close(self) -> None:
        pass


def event_to_dict(e: AuditEvent) -> dict[str, Any]:
    return {
        "id": e.id, "fingerprint": e.fingerprint_id, "query_id": e.query_id,
        "dag_id": e.dag_id, "task_id": e.task_id, "run_id": e.run_id,
        "warehouse_name": e.warehouse_name, "cost_usd": e.cost_usd, "baseline_usd": e.baseline_usd,
        "waste_usd": e.waste_usd, "ratio": e.ratio, "severity": e.severity,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
    }


def suggestion_to_dict(x: Suggestion) -> dict[str, Any]:
    return {
        "id": x.id, "audit_event_id": x.audit_event_id, "fingerprint": x.fingerprint_id,
        "status": x.status, "diagnosis": x.diagnosis, "strategy": x.strategy,
        "estimated_savings_pct": x.estimated_savings_pct, "original_sql": x.original_sql,
        "suggested_sql": x.suggested_sql, "validation_notes": x.validation_notes,
        "provider": x.provider, "model": x.model, "latency_ms": x.latency_ms,
        "created_at": x.created_at.isoformat() if x.created_at else None,
        "decided_at": x.decided_at.isoformat() if x.decided_at else None,
        "decided_by": x.decided_by, "decision_note": x.decision_note,
    }
