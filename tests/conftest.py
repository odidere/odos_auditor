import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pulseflow.backend.models import Base, QueryFingerprint


@pytest.fixture
def db_session():
    """Sets up an in-memory SQLite DB for isolated testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def aged_fingerprint(db_session):
    """Seeds a fingerprint with high execution count to bypass warm-up logic."""
    fp = QueryFingerprint(
        hash_id="sig1",
        avg_cost_usd=1.0,
        execution_count=10,  # Bypass the > 5 guardrail
        avg_duration_sec=5.0
    )
    db_session.add(fp)
    db_session.commit()
    return fp


class MockSF:
    def __init__(self):
        self.return_data = []

    def set_return_data(self, data: list):
        """Allows the test to define what Snowflake 'returns'."""
        self.return_data = data

    def fetch_attributed_costs(self, lookback: int):
        """Simulates the Snowflake fetch logic used by the Auditor."""
        return self.return_data


@pytest.fixture
def mock_sf():
    return MockSF()
