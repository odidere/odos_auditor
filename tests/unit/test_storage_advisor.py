from unittest.mock import MagicMock, patch

import pytest

from odos.backend.storage_advisor import StorageAdvisor


@pytest.fixture
def mock_engine_init():
    """Prevents real DB connection during Advisor init."""
    with patch("odos.backend.db.get_db_engine") as mock:
        yield mock


@patch("snowflake.connector.connect")
def test_advisor_ghost_query_structure(mock_connect, mock_engine_init):
    """
    Ensures the advisor can be initialized and structure validated 
    without a real Snowflake connection.
    """
    # 1. Setup Mock Connection
    mock_conn = MagicMock()
    mock_connect.return_value = mock_conn

    # 2. ACT: Instantiate (This previously crashed)
    advisor = StorageAdvisor()

    # 3. ASSERT: Verify the advisor didn't crash and used our mock
    assert advisor is not None
    mock_connect.assert_called_once()
