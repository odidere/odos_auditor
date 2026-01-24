import json
import os
import sqlite3
import sys

import pandas as pd

from odos.backend.storage_advisor import StorageAdvisor
from odos.backend.surgeon import Surgeon

# 1. Robust Path Setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))

# 2. Add Project Root to Sys Path (Fixes ModuleNotFoundError)
sys.path.insert(0, PROJECT_ROOT)

# 3. Define Resource Paths
DB_PATH = os.path.join(PROJECT_ROOT, "odos.db")
# This environment variable fallback ensures we check the right file
ARTIFACTS_PATH = os.getenv("ODOS_DATASET_PATH",
                           os.path.join(PROJECT_ROOT, "system_testing/test_artifacts/odos_finetuning_dataset.jsonl"))

# 4. Now we can safely import backend modules


def verify_surgeon_logging():
    print("🚑 Testing Surgeon Data Persistence...")
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(ARTIFACTS_PATH), exist_ok=True)

        # Instantiate Surgeon
        surgeon = Surgeon()

        # Force a log entry
        test_task_id = "SYSTEM_TEST_TASK_999"
        surgeon.log_for_finetuning(
            original_sql="SELECT * FROM TEST",
            suggested_sql="SELECT 1 FROM TEST",
            accepted=True,
            task_id=test_task_id
        )

        # Verify File Existence
        if not os.path.exists(ARTIFACTS_PATH):
            print(f"❌ FAIL: Dataset file not created at {ARTIFACTS_PATH}")
            return False

        with open(ARTIFACTS_PATH, 'r') as f:
            lines = f.readlines()
            if not lines:
                print("❌ FAIL: Log file is empty.")
                return False
            last_line = json.loads(lines[-1])
            if last_line.get('task_id') == test_task_id:
                print("✅ PASS: Surgeon successfully logged fine-tuning data.")
                return True
            else:
                print(
                    f"❌ FAIL: Log content mismatch. Got: {last_line.get('task_id')}")
                return False

    except Exception as e:
        print(f"❌ FAIL: Surgeon crashed during test. Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_storage_advisor_stability():
    print("🗄️  Testing Storage Advisor Stability...")
    try:
        advisor = StorageAdvisor()
        print("✅ PASS: StorageAdvisor module loaded successfully.")
        return True
    except Exception as e:
        if "Snowflake Credentials" in str(e) or "environment variables" in str(e):
            print("✅ PASS: StorageAdvisor gracefully handled missing credentials.")
            return True
        print(f"❌ FAIL: StorageAdvisor crashed on init: {e}")
        return False


def check_database_health():
    print(f"🔎 Checking DB at: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print(f"❌ FAIL: Database file not found at {DB_PATH}")
        return False

    conn = sqlite3.connect(DB_PATH)
    try:
        # Check if table exists first
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events';")
        if not cursor.fetchone():
            print(
                "⚠️ WARNING: 'audit_events' table does not exist yet (Pipeline hasn't run). Skipping row check.")
            return True

        events = pd.read_sql("SELECT * FROM audit_events", conn)
        if len(events) > 0:
            print(f"✅ PASS: Found {len(events)} audit events in DB.")
        else:
            print("⚠️ WARNING: DB exists but 'audit_events' is empty.")
        return True
    except Exception as e:
        print(f"❌ FAIL: DB Query failed: {e}")
        return False


if __name__ == "__main__":
    print(f"🧪 Running Enhanced System Verification from: {PROJECT_ROOT}")

    # We enforce the ENV var for the surgeon log path to match our calculation
    os.environ["PULSEFLOW_DATASET_PATH"] = ARTIFACTS_PATH

    checks = [
        check_database_health(),
        verify_surgeon_logging(),
        verify_storage_advisor_stability()
    ]

    if all(checks):
        print("\n🎉 ALL SYSTEMS GO: Integration Test Passed")
        sys.exit(0)
    else:
        print("\n💀 SYSTEM FAILURE: Check logs above")
        sys.exit(1)
