"""The single Odos schema. Every table Odos reads or writes is defined here.

Create it with ``odos init-db`` (or :func:`odos.backend.db.init_db`).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (Column, Date, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CostCenter(Base):
    """Maps DAG ids to business departments for chargeback."""
    __tablename__ = "cost_centers"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    pattern = Column(String(255), nullable=False)  # SQL LIKE pattern on dag_id, e.g. 'mktg_%'
    daily_budget_usd = Column(Float, default=100.0)
    events = relationship("AuditEvent", back_populates="cost_center")


class QueryFingerprint(Base):
    """Baseline for one query shape (see odos.fingerprint)."""
    __tablename__ = "query_fingerprints"
    hash_id = Column(String(64), primary_key=True)
    source = Column(String(32), default="unknown")
    sql_sample = Column(Text)  # literals redacted unless ai.send_literals is true
    tables = Column(Text)      # comma-separated
    avg_cost_usd = Column(Float, default=0.0)
    dev_cost_usd = Column(Float, default=0.0)  # smoothed absolute deviation
    avg_duration_sec = Column(Float, default=0.0)
    execution_count = Column(Integer, default=0)
    last_query_start = Column(DateTime)  # newest run already processed (idempotency)
    last_seen = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)


class AuditEvent(Base):
    """One query run whose cost broke away from its fingerprint's baseline."""
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True)
    fingerprint_id = Column(String(64), ForeignKey("query_fingerprints.hash_id"), index=True)
    query_id = Column(String(128), unique=True)
    cost_center_id = Column(Integer, ForeignKey("cost_centers.id"), nullable=True)
    dag_id = Column(String(255), index=True)
    task_id = Column(String(255))
    run_id = Column(String(255))
    warehouse_name = Column(String(255))
    cost_usd = Column(Float)
    baseline_usd = Column(Float)
    waste_usd = Column(Float)
    ratio = Column(Float)
    duration_sec = Column(Float)
    severity = Column(String(16))  # MEDIUM, HIGH, CRITICAL
    timestamp = Column(DateTime, default=utcnow)  # query start (or detection) time
    cost_center = relationship("CostCenter", back_populates="events")
    suggestions = relationship("Suggestion", back_populates="audit_event")


Index("idx_dag_timestamp", AuditEvent.dag_id, AuditEvent.timestamp)


class Suggestion(Base):
    """An AI-proposed rewrite. Odos never executes it: a person approves or rejects it."""
    __tablename__ = "suggestions"
    id = Column(Integer, primary_key=True)
    audit_event_id = Column(Integer, ForeignKey("audit_events.id"), index=True)
    fingerprint_id = Column(String(64), ForeignKey("query_fingerprints.hash_id"), index=True)
    original_sql = Column(Text)   # exactly what was sent to the model
    suggested_sql = Column(Text)
    diagnosis = Column(Text)
    strategy = Column(String(255))
    estimated_savings_pct = Column(Integer)
    provider = Column(String(64))
    model = Column(String(128))
    latency_ms = Column(Integer)
    # PENDING (valid, awaiting review), INVALID (failed validation),
    # FAILED (no provider answered), APPROVED, REJECTED
    status = Column(String(16), default="PENDING", index=True)
    validation_notes = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    decided_at = Column(DateTime)
    decided_by = Column(String(255))
    decision_note = Column(Text)
    audit_event = relationship("AuditEvent", back_populates="suggestions")


class DailyCost(Base):
    """Total attributed query cost per day (feeds the financial summary)."""
    __tablename__ = "daily_costs"
    day = Column(Date, primary_key=True)
    source = Column(String(32), primary_key=True)
    cost_usd = Column(Float, default=0.0)
    query_count = Column(Integer, default=0)


class PipelineRun(Base):
    """One execution of a tracked pipeline (written by the agent)."""
    __tablename__ = "pipeline_runs"
    id = Column(Integer, primary_key=True)
    pipeline_name = Column(String(255), index=True)
    dag_id = Column(String(255))
    task_id = Column(String(255))
    run_id = Column(String(255))
    trace_id = Column(String(64))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    duration_sec = Column(Float)
    status = Column(String(16))  # SUCCESS / FAILED
    rows_processed = Column(Integer, default=0)
    throughput_rows_per_sec = Column(Float, default=0.0)
    error_message = Column(Text)
    stack_trace = Column(Text)
    ai_diagnosis = Column(Text)
    ai_suggested_fix = Column(Text)


class LineageNode(Base):
    __tablename__ = "lineage_nodes"
    node_id = Column(String(255), primary_key=True)
    node_type = Column(String(32))  # JOB, TABLE, DASHBOARD, ML_MODEL
    layer = Column(String(32))


class LineageEdge(Base):
    __tablename__ = "lineage_edges"
    source_node = Column(String(255), primary_key=True)
    target_node = Column(String(255), primary_key=True)
    __table_args__ = (UniqueConstraint("source_node", "target_node", name="uq_lineage_edge"),)


def as_date(value: datetime | date | None) -> date:
    if value is None:
        return utcnow().date()
    return value.date() if isinstance(value, datetime) else value
