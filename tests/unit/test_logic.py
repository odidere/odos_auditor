import pytest

from pulseflow.backend.audit_logic import EfficiencyAuditor


def test_zombie_detection():
    """
    Test that short duration + high cost triggers a ZOMBIE alert.
    """
    # FIX: Use Uppercase keys to match Snowflake standard output
    raw_data = [{
        'DAG_ID': 'dag_a',
        'TASK_ID': 'task_a',
        'TRUE_COST_USD': 1.00,
        'DURATION_SEC': 5,       # 5 seconds (Zombie!)
        'EFFICIENCY_TAG': 'POTENTIAL_WASTE',
        'QUERY_ID': 'q1',        # Auditor needs this for counting
        'fingerprint': 'abc'
    }]

    auditor = EfficiencyAuditor(raw_data)
    report = auditor.generate_zombie_report()

    # Debugging print if test fails again
    print(f"Report Status: {report.get('status')}")

    # Assertions
    assert report['status'] in ['warning', 'critical']
    assert report['total_daily_waste_usd'] > 0


def test_clean_report():
    """
    Test that efficient tasks return a clean status.
    """
    raw_data = [{
        'DAG_ID': 'dag_b',
        'TASK_ID': 'task_b',
        'TRUE_COST_USD': 0.10,
        'DURATION_SEC': 300,     # 5 mins (Efficient)
        'EFFICIENCY_TAG': 'EFFICIENT',
        'QUERY_ID': 'q2',
        'fingerprint': 'xyz'
    }]

    auditor = EfficiencyAuditor(raw_data)
    report = auditor.generate_zombie_report()

    assert report['status'] == 'clean'
    assert report['total_daily_waste_usd'] == 0.0
