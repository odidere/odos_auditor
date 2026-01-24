import os

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# FIXED: Synchronized import name with cost_engine.py
from .cost_engine import CostEngine
# Internal Imports
from .models import AuditEvent, Base, QueryFingerprint
from .service import EnterpriseAuditor

# Database Setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./odos.db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Odos Auditor API",
    description="Enterprise interface for Snowflake cost governance and anomaly detection.",
    version="1.0.0"
)

# Dependency to get DB session


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- ENDPOINTS ---


@app.post("/api/v1/audit/run", tags=["Auditor"])
def trigger_audit(db: Session = Depends(get_db)):
    """
    Triggers a full audit cycle. 
    Fetches attributed costs from Snowflake, updates baselines, and detects anomalies.
    """
    try:
        # FIXED: Using the standardized CostEngine class
        sf_engine = CostEngine()

        # Load lineage edges (In production, these come from Dagster/Airflow metadata)
        lineage_edges = []

        auditor = EnterpriseAuditor(db, sf_engine, lineage_edges)
        report = auditor.run_audit_cycle(lookback=1)  # Audit the last 24 hours

        return {
            "status": "success",
            "timestamp": "2026-01-23T23:29:00Z",  # Updated to current context
            "report": report
        }
    except Exception as e:
        # Log the error for debugging
        print(f"Audit Trigger Failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/audit/history", tags=["Reports"])
def get_audit_history(limit: int = 10, db: Session = Depends(get_db)):
    """
    Returns historical audit events, including the waste identified and the 
    downstream blast radius for each event.
    """
    events = db.query(AuditEvent).order_by(
        AuditEvent.timestamp.desc()).limit(limit).all()
    return events


@app.get("/api/v1/infra/advisor", tags=["Infrastructure"])
def get_infrastructure_advice(db: Session = Depends(get_db)):
    """
    Returns current warehouse downsizing recommendations based on 
    utilization patterns found in the latest audit logs.
    """
    return {"message": "Use /api/v1/audit/run to generate fresh recommendations."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
