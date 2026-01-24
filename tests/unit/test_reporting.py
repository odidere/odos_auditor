import pandas as pd
import pytest

from odos.backend.reporting import calculate_efficiency, generate_pdf_binary


def test_efficiency_calculation():
    """
    Verifies the core ROI logic.
    Handles the floating point precision mismatch found in previous runs.
    """
    # Standard cases
    assert calculate_efficiency(1000, 200) == 80.0
    assert calculate_efficiency(0, 0) == 100.0
    assert calculate_efficiency(100, 100) == 0.0

    # FIX: Use pytest.approx for repeating decimals or floating point math
    # 333.33 and 111.11 leads to 66.66666666666666
    assert calculate_efficiency(
        333.33, 111.11) == pytest.approx(66.67, abs=1e-2)


def test_pdf_generation_content():
    metrics = {
        "burn": 50000.0,
        "waste": 5000.0,
        "budget": 2000.0,
        "efficiency": 90.0
    }

    anomalies = pd.DataFrame([
        {'task_id': 'marketing_load_v1', 'severity': 'HIGH', 'waste_usd': 50.0}
    ])

    pdf_bytes = generate_pdf_binary(metrics, anomalies, "Prowess Pictures")

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF")
