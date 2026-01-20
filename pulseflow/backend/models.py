from datetime import datetime

from sqlalchemy import (Column, DateTime, Float, ForeignKey, Index, Integer,
                        String)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class CostCenter(Base):
    """Enables financial chargebacks to specific business departments."""
    __tablename__ = "cost_centers"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    pattern = Column(String, nullable=False)  # e.g. 'mktg_%' matches dag_ids
    daily_budget_usd = Column(Float, default=100.0)
    events = relationship("AuditEvent", back_populates="cost_center")


class QueryFingerprint(Base):
    """The persistent baseline for a specific logical SQL structure."""
    __tablename__ = "query_fingerprints"
    hash_id = Column(String, primary_key=True)  # Normalized SQL hash
    avg_cost_usd = Column(Float, default=0.0)
    avg_duration_sec = Column(Float, default=0.0)
    execution_count = Column(Integer, default=0)
    last_seen = Column(DateTime, default=datetime.utcnow)


class AuditEvent(Base):
    """Log of specific waste events for reporting and remediation."""
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True)
    fingerprint_id = Column(String, ForeignKey("query_fingerprints.hash_id"))
    cost_center_id = Column(Integer, ForeignKey(
        "cost_centers.id"), nullable=True)
    dag_id = Column(String, index=True)
    task_id = Column(String)
    waste_usd = Column(Float)
    severity = Column(String)  # LOW, MEDIUM, HIGH, CRITICAL
    timestamp = Column(DateTime, default=datetime.utcnow)
    cost_center = relationship("CostCenter", back_populates="events")


# Index for fast time-series analysis
Index('idx_dag_timestamp', AuditEvent.dag_id, AuditEvent.timestamp)
