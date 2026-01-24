# system_testing/fail_pipeline.py
import time

from odos.agent.instrument import track_pipeline


@track_pipeline(name="broken_etl_job")
def run_fail():
    print("Starting job...")
    time.sleep(1)
    # Simulate a crash
    raise ConnectionError(
        "ConnectionTimeout: Failed to reach Snowflake host 192.168.1.5")


if __name__ == "__main__":
    try:
        run_fail()
    except:
        pass  # We just want Odos to catch it
