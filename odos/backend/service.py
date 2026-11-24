"""The audit cycle: fetch costs -> update baselines -> flag anomalies -> advise.

Re-running a cycle over an overlapping window is safe: runs at or before a
fingerprint's ``last_query_start`` are skipped, and audit events are unique
per query id.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from odos.backend.advisor import WarehouseAdvisor
from odos.backend.detection import Baseline, DetectionSettings, evaluate, update
from odos.backend.lineage import ImpactAnalyzer
from odos.backend.models import AuditEvent, DailyCost, QueryFingerprint, as_date, utcnow
from odos.backend.sql_safety import redact_sql
from odos.config import section
from odos.fingerprint import tables_in
from odos.sources.base import CostRecord, normalize_records


class EnterpriseAuditor:
    def __init__(self, db: Session, source: Any, lineage_edges: list[tuple[str, str]] | None = None,
                 settings: DetectionSettings | None = None):
        self.db = db
        self.source = source
        self.lineage = ImpactAnalyzer(lineage_edges)
        self.settings = settings or DetectionSettings.from_config(section("detection"))
        ai = section("ai")
        self.keep_literals = bool(ai.get("send_literals", False))
        self.dialect = ai.get("dialect", "snowflake")

    def _fingerprint_row(self, record: CostRecord) -> QueryFingerprint:
        fp = self.db.get(QueryFingerprint, record.fingerprint)
        if fp is None:
            sample = record.query_text or ""
            if sample and not self.keep_literals:
                sample = redact_sql(sample, self.dialect)
            fp = QueryFingerprint(
                hash_id=record.fingerprint,
                source=record.source,
                sql_sample=sample or None,
                tables=",".join(sorted(tables_in(record.query_text or "", self.dialect))) or None,
                avg_cost_usd=0.0, dev_cost_usd=0.0, avg_duration_sec=0.0, execution_count=0,
            )
            self.db.add(fp)
        return fp

    def _add_daily_cost(self, record: CostRecord) -> None:
        key = (as_date(record.start_time), record.source)
        row = self.db.get(DailyCost, key)
        if row is None:
            row = DailyCost(day=key[0], source=key[1], cost_usd=0.0, query_count=0)
            self.db.add(row)
        row.cost_usd = (row.cost_usd or 0.0) + record.cost_usd
        row.query_count = (row.query_count or 0) + 1

    def run_audit_cycle(self, lookback: int = 1) -> dict[str, Any]:
        records = normalize_records(self.source.fetch_attributed_costs(lookback),
                                    getattr(self.source, "name", "unknown"))
        records.sort(key=lambda r: (r.start_time is None, r.start_time or 0))
        results: dict[str, Any] = {"processed": 0, "skipped": 0, "anomalies": [], "right_sizing": []}

        for record in records:
            fp = self._fingerprint_row(record)
            if record.start_time and fp.last_query_start and record.start_time <= fp.last_query_start:
                results["skipped"] += 1
                continue
            if record.query_id and self.db.scalar(
                    select(AuditEvent.id).where(AuditEvent.query_id == record.query_id)):
                results["skipped"] += 1
                continue

            baseline = Baseline(fp.avg_cost_usd or 0.0, fp.dev_cost_usd or 0.0, fp.execution_count or 0)
            verdict = evaluate(record.cost_usd, baseline, self.settings)
            if verdict.is_anomaly:
                event = AuditEvent(
                    fingerprint_id=fp.hash_id, query_id=record.query_id,
                    dag_id=record.dag_id, task_id=record.task_id, run_id=record.run_id,
                    warehouse_name=record.warehouse_name, cost_usd=record.cost_usd,
                    baseline_usd=baseline.mean, waste_usd=verdict.waste_usd, ratio=verdict.ratio,
                    duration_sec=record.duration_sec, severity=verdict.severity,
                    timestamp=record.start_time or utcnow(),
                )
                self.db.add(event)
                node = record.task_id or record.dag_id or fp.hash_id
                results["anomalies"].append({
                    "fingerprint": fp.hash_id,
                    "query_id": record.query_id,
                    "dag": record.dag_id,
                    "task": record.task_id,
                    "cost_usd": round(record.cost_usd, 4),
                    "baseline_usd": round(baseline.mean, 4),
                    "waste": round(verdict.waste_usd, 4),
                    "ratio": round(verdict.ratio or 0.0, 2),
                    "severity": verdict.severity,
                    "blast_radius": self.lineage.calculate_blast_radius(node),
                    "delay_risk": self.lineage.get_critical_path_delay(node, record.duration_sec),
                })

            new = update(baseline, record.cost_usd, self.settings, flagged=verdict.is_anomaly)
            fp.avg_cost_usd, fp.dev_cost_usd, fp.execution_count = new.mean, new.deviation, new.count
            n = fp.execution_count
            fp.avg_duration_sec = ((fp.avg_duration_sec or 0.0) * (n - 1) + record.duration_sec) / n
            fp.last_seen = utcnow()
            if record.start_time:
                fp.last_query_start = record.start_time
            self._add_daily_cost(record)
            results["processed"] += 1
            self.db.flush()

        if hasattr(self.source, "fetch_warehouse_usage"):
            usage = self.source.fetch_warehouse_usage(lookback)
            advisor = WarehouseAdvisor(usage, float(section("costs").get("compute_credit_price", 3.0)),
                                       section("advisor"))
            results["right_sizing"] = advisor.recommendations()

        self.db.commit()
        return results
