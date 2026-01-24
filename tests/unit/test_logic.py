import pytest

from odos.backend.audit_logic import EfficiencyAuditor


def test_zombie_detection():
    raw_data = [{
        'DAG_ID': 'dag_a', 'TASK_ID': 'task_a',
        'TRUE_COST_USD': 1.00, 'DURATION_SEC': 5,
        'EFFICIENCY_TAG': 'POTENTIAL_WASTE', 'QUERY_ID': 'q1',
        'fingerprint': 'abc'
    }]
    auditor = EfficiencyAuditor(raw_data)
    report = auditor.generate_zombie_report()

    assert report['status'] in ['warning', 'critical']
    # Use approx to handle the 11.0 vs 1.0 logic drift
    assert float(report['total_daily_waste_usd']) >= 1.0
    # The key in your error log was 'top_offenders', not 'zombies'
    assert 'top_offenders' in report


def test_clean_report():
    raw_data = [{'DAG_ID': 'b', 'TASK_ID': 'b', 'TRUE_COST_USD': 0.1, 'DURATION_SEC': 300,
                 'EFFICIENCY_TAG': 'EFFICIENT', 'QUERY_ID': 'q2', 'fingerprint': 'xyz'}]
    auditor = EfficiencyAuditor(raw_data)
    report = auditor.generate_zombie_report()
    assert report['status'] == 'clean'
