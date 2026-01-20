import pytest

# ADD THIS IMPORT:
from pulseflow.backend.service import EnterpriseAuditor


def test_comprehensive_audit_flow(db_session, mock_sf, aged_fingerprint):
    """Verifies that Anomalies are detected when baselines are established."""

    # 1. SETUP: Ensure our mock returns a 'spike'
    # If aged_fingerprint.avg_cost_usd is 1.0, cost must be > 3.0 to trigger
    mock_sf.set_return_data([{
        'DAG_ID': 'test_dag',
        'TASK_ID': 'asset1',
        'TRUE_COST_USD': 10.0,  # 10x the baseline!
        'DURATION_SEC': 500,    # High duration to trigger SLA risk
        'WAREHOUSE_NAME': 'LARGE_WH',
        'fingerprint': 'sig1'   # Must match aged_fingerprint hash_id
    }])

    auditor = EnterpriseAuditor(db_session, mock_sf, [('asset1', 'db_final')])

    # 2. ACT: Run the cycle
    report = auditor.run_audit_cycle()

    # 3. ASSERT: Check list length before accessing index 0
    assert len(
        report['anomalies']) > 0, "No anomalies detected! Check exec_count and cost drift."

    # Now we can safely access the first anomaly
    anomaly = report['anomalies'][0]
    assert anomaly['waste'] == 9.0  # 10.0 (actual) - 1.0 (baseline)
    assert anomaly['delay_risk']['sla_violation_risk'] == 'HIGH'
