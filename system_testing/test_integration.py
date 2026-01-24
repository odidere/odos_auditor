import os
import time
import unittest

import psycopg2
import yaml

from odos.agent.instrument import track_pipeline
from odos.backend.db import _get_db_creds

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config.yaml")
with open(CONFIG_PATH, "r") as f:
    CONF = yaml.safe_load(f)


class TestOdosIntegration(unittest.TestCase):

    def setUp(self):
        # Instead of using raw CONF['database'], use our priority-ordered helper
        creds = _get_db_creds()
        self.conn = psycopg2.connect(
            host=creds['host'],
            port=creds['port'],
            user=creds['user'],
            password=creds['pass'],  # This maps to POSTGRES_PASSWORD
            dbname=creds['db']
        )

    def tearDown(self):
        self.conn.close()

    def test_pipeline_success_tracking(self):
        """Test if a successful run is logged to Postgres."""
        print("\n🧪 Testing Successful Pipeline Tracking...")

        test_job_name = f"test_job_success_{int(time.time())}"

        @track_pipeline(name=test_job_name)
        def successful_job():
            time.sleep(0.1)
            return 500  # Processed 500 rows

        # Run the job
        successful_job()

        # Verify in DB
        self.cur.execute(
            f"SELECT rows_processed, status FROM pipeline_runs WHERE pipeline_name = '{test_job_name}'")
        row = self.cur.fetchone()

        self.assertIsNotNone(row, "❌ Trace not found in Postgres!")
        self.assertEqual(row[0], 500, "❌ Row count mismatch!")
        self.assertEqual(row[1], 'SUCCESS', "❌ Status mismatch!")
        print("✅ Success Tracking Verified.")

    def test_pipeline_failure_capture(self):
        """Test if Stack Traces are captured in Postgres."""
        print("\n🧪 Testing Failure & Stack Trace Capture...")

        test_job_name = f"test_job_fail_{int(time.time())}"
        error_msg = "Simulated Connection Timeout"

        @track_pipeline(name=test_job_name)
        def failing_job():
            raise ConnectionError(error_msg)

        # Run job and expect crash
        try:
            failing_job()
        except ConnectionError:
            pass  # Expected

        # Verify in DB
        self.cur.execute(
            f"SELECT status, error_message, stack_trace FROM pipeline_runs WHERE pipeline_name = '{test_job_name}'"
        )
        row = self.cur.fetchone()

        self.assertIsNotNone(row, "❌ Failed run not logged!")
        self.assertEqual(row[0], 'FAILED')
        self.assertIn(error_msg, row[1], "❌ Error message not captured!")
        self.assertIn("Traceback", row[2], "❌ Stack trace not captured!")
        print("✅ AI SRE Data Capture Verified.")


if __name__ == '__main__':
    unittest.main()
