import pandas as pd
import pytest

from pulseflow.backend.reporting import (calculate_efficiency,
                                         generate_pdf_binary)


def test_efficiency_calculation():
    assert calculate_efficiency(1000, 200) == 80.0
    assert calculate_efficiency(0, 0) == 100.0
    assert calculate_efficiency(100, 100) == 0.0


def test_pdf_generation_content():
    metrics = {"burn": 50000.0, "waste": 5000.0,
               "budget": 2000.0, "efficiency": 90.0}

    # Create a dummy dataframe matching the expected structure
    anomalies = pd.DataFrame([
        {'task_id': 'test_task', 'severity': 'HIGH', 'waste_usd': 50.0}
    ])

    pdf_bytes = generate_pdf_binary(metrics, anomalies, "Test Project")

    # Assert we got valid binary data back
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0
    assert b"%PDF" in pdf_bytes
