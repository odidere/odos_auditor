import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from odos.backend.models import Base, QueryFingerprint


@pytest.fixture
def db_session():
    """
    Sets up an in-memory SQLite DB for isolated logic testing.
    Uses StaticPool to ensure the connection stays open during the test lifecycle.
    """
    # SQLite in-memory requires StaticPool to maintain the schema between setup and test
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def aged_fingerprint(db_session):
    """
    Seeds a fingerprint with established baselines.
    This bypasses the 'warm-up' guardrails (execution_count > 5).
    """
    fp = QueryFingerprint(
        hash_id="sig1",
        avg_cost_usd=1.0,
        execution_count=10,
        avg_duration_sec=5.0
    )
    db_session.add(fp)
    db_session.commit()
    # Expire to ensure the session fetches fresh data during the test
    db_session.refresh(fp)
    return fp


class MockSF:
    """
    Mock Snowflake Provider to simulate warehouse cost and duration data.
    """

    def __init__(self):
        self.return_data = []

    def set_return_data(self, data: list):
        """Define the Snowflake 'response' for the current test case."""
        self.return_data = data

    def fetch_attributed_costs(self, lookback_days: int):
        """Simulates the raw Snowflake fetch used by the EnterpriseAuditor."""
        return self.return_data


@pytest.fixture
def mock_sf():
    """Provides a fresh Snowflake mock for every test."""
    return MockSF()
