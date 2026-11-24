from unittest.mock import MagicMock

import pytest

from odos.backend.reporting import calculate_efficiency


def test_efficiency_calculation():
    assert calculate_efficiency(1000, 200) == 80.0
    assert calculate_efficiency(0, 0) == 100.0
    assert calculate_efficiency(100, 100) == 0.0
    assert calculate_efficiency(333.33, 111.11) == pytest.approx(66.67, abs=1e-2)


def test_pdf_generation():
    pytest.importorskip("fpdf")
    from odos.backend.reporting import generate_pdf_binary

    pdf = generate_pdf_binary({"burn": 50000.0, "waste": 5000.0, "budget": 2000.0, "efficiency": 90},
                              [{"task_id": "marketing_load", "severity": "HIGH", "waste_usd": 50.0}], "Demo")
    assert pdf.startswith(b"%PDF")


def test_storage_advisor_connects_lazily_and_binds_parameters():
    pytest.importorskip("pandas")
    from odos.backend.storage_advisor import StorageAdvisor

    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.description = [("TABLE_NAME",), ("SIZE_GB",)]
    cursor.fetchall.return_value = [("db.s.t", 2.0)]
    advisor = StorageAdvisor(conn=conn)
    df = advisor.find_cold_data_candidates()
    sql, params = cursor.execute.call_args[0]
    assert "%(pattern)s" in sql and params["pattern"] == ".*(LOG|EVENT|HISTORY).*"
    assert list(df.columns) == ["table_name", "size_gb"]


def test_storage_policy_validates_names_and_never_deletes_by_default():
    from odos.backend.storage_advisor import StorageAdvisor

    policy = StorageAdvisor(conn=object()).generate_storage_policy("analytics.events_log")
    assert "-- DELETE FROM analytics.events_log" in policy
    assert "\nDELETE" not in policy
    with pytest.raises(ValueError):
        StorageAdvisor(conn=object()).generate_storage_policy("x; DROP TABLE y")
