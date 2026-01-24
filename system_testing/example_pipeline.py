import random
import sys
import time

# The core instrumentation for the Odos Data Engineering Operating System
from odos.agent.instrument import track_pipeline


@track_pipeline(name="real_daily_ingest")
def process_data_batch():
    """
    Consolidated Production Simulation.
    Demonstrates successful processing, latency tracking, and failure capture.
    """
    print("🔄 Initializing ETL Job: real_daily_ingest...")

    # 1. Simulate Latency (Captured in the UI Command Center)
    time.sleep(random.uniform(0.5, 2.0))

    # 2. Simulate random failure (Target for integration test failure capture)
    if random.random() < 0.15:
        # This exception and its stack trace are automatically logged to Postgres
        raise ConnectionError("FAILED: Salesforce API Gateway Timeout (504)")

    # 3. Success Metric (Feeds the 'Rows' column in the UI)
    processed_count = random.randint(10000, 25000)
    print(f"✅ Batch processing complete. Records handled: {processed_count}")

    return processed_count


if __name__ == "__main__":
    try:
        # Running the instrumented function
        process_data_batch()
        print("🚀 Status: SUCCESS")
    except Exception as e:
        # The @track_pipeline decorator has already logged the error
        print(f"🛑 Status: RECORDED FAILURE - {e}")
        sys.exit(1)
