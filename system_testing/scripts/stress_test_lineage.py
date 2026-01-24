from odos.backend.db import get_db_connection
import os
import random
import sys

# Ensure root is in path
sys.path.append(os.getcwd())


def generate_messy_lineage():
    print("🕸️  Generating Complex Lineage Stress Test...")
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    layers = ['RAW', 'ETL', 'SILVER', 'TRANSFORM', 'GOLD', 'BI']

    # 1. Create a lot of nodes
    for i in range(35):
        layer = random.choice(layers)
        node_id = f"node_{i:02d}_{layer.lower()}"
        node_type = "TABLE" if i % 3 != 0 else "JOB"

        cur.execute("""
            INSERT INTO lineage_nodes (node_id, node_type, layer)
            VALUES (%s, %s, %s)
            ON CONFLICT (node_id) DO UPDATE SET layer = EXCLUDED.layer
        """, (node_id, node_type, layer))

    # 2. Create complex edges (Randomized but somewhat layered)
    cur.execute("SELECT node_id, layer FROM lineage_nodes")
    all_nodes = cur.fetchall()

    for _ in range(60):
        src = random.choice(all_nodes)
        tgt = random.choice(all_nodes)

        # Simple rule to keep it mostly flowing forward (optional for stress test)
        if src[0] != tgt[0]:
            cur.execute("""
                INSERT INTO lineage_edges (source_node, target_node)
                VALUES (%s, %s) ON CONFLICT DO NOTHING
            """, (src[0], tgt[0]))

    conn.close()
    print("✅ Stress Test data seeded. Refresh your UI!")


if __name__ == "__main__":
    generate_messy_lineage()
