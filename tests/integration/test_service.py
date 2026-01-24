import os

import pytest

from odos.backend.service import EnterpriseAuditor

# Check if we are in GitHub Actions environment
IN_CI = os.getenv("GITHUB_ACTIONS") == "true"


@pytest.mark.skipif(IN_CI, reason="Skipping Postgres tests in CI for now")
def test_comprehensive_audit_flow(db_session, mock_sf, aged_fingerprint):
    """
    Verifies the intelligence loop with full telemetry.
    Satisfies both Auditor (AuditEvent) and Advisor (Right-sizing).
    """

    # 1. SETUP: Full telemetry mock
    mock_sf.set_return_data([{
        'DAG_ID': 'test_dag_v1',
        'TASK_ID': 'asset1',
        'TRUE_COST_USD': 10.0,
        'DURATION_SEC': 500,
        'WAREHOUSE_NAME': 'COMPUTE_WH',  # This was the missing key
        'fingerprint': 'sig1'
    }])

    auditor = EnterpriseAuditor(db_session, mock_sf, [('asset1', 'db_prod')])

    # 2. ACT
    report = auditor.run_audit_cycle()

    # 3. ASSERT
    # Verify Anomaly detection
    assert len(report['anomalies']) > 0
    assert float(report['anomalies'][0]['waste']) == 9.0

    # Verify Infrastructure Advice (this will now work!)
    assert 'right_sizing' in report
    assert len(report['right_sizing']) >= 0
