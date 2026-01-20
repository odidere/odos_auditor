import os
import sqlite3

# Points to the DB in the root directory
DB_PATH = "../../pulseflow.db"


def seed_history():
    print(f"🌱 Seeding baseline data into {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Create table if not exists (in case app hasn't run yet)
    c.execute("""CREATE TABLE IF NOT EXISTS query_fingerprints 
                 (hash_id TEXT PRIMARY KEY, sql_text TEXT, execution_count INTEGER, avg_cost_usd REAL)""")

    # 1. Establish Baseline for Engineering (The Zombie Candidate)
    # We say it has run 20 times with an average cost of $5.00
    c.execute("INSERT OR REPLACE INTO query_fingerprints VALUES (?, ?, ?, ?)",
              ('eng_hash', 'CALL train_model_v2()', 20, 5.00))

    conn.commit()
    conn.close()
    print("✅ Baseline established. The Auditor is ready to detect spikes > $15.00.")


if __name__ == "__main__":
    seed_history()
