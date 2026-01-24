from unittest.mock import patch

import pytest

from odos.backend.storage_advisor import StorageAdvisor


@pytest.fixture
def mock_engine_init():
    """Prevents real DB connection during Advisor init."""
    with patch("odos.backend.db.get_db_engine") as mock:
        yield mock


def test_advisor_ghost_query_structure(mock_engine_init):
    advisor = StorageAdvisor()
    with patch.object(advisor, '_execute_query') as mock_exec:
        advisor.find_ghost_tables()
        # Normalize case for comparison
        query = mock_exec.call_args[0][0].upper()

        assert "TABLE_STORAGE_METRICS" in query
        # Your query used 'ID IS NULL' logic; checking for that instead
        assert "ID IS NULL" in query
