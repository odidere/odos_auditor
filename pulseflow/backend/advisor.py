import pandas as pd


class WarehouseAdvisor:
    """
    Scans query logs for infrastructure inefficiencies.
    Implements Right-Sizing recommendations.
    """
    WH_SIZE_MAP = {
        'X-SMALL': 1, 'SMALL': 2, 'MEDIUM': 4,
        'LARGE': 8, 'X-LARGE': 16, '2X-LARGE': 32
    }

    def __init__(self, raw_data):
        self.df = pd.DataFrame(raw_data)

    def analyze_warehouse_efficiency(self):
        if self.df.empty:
            return []
        recommendations = []

        # Aggregate patterns by warehouse name
        wh_stats = self.df.groupby('WAREHOUSE_NAME').agg({
            'DURATION_SEC': ['mean', 'max', 'count'],
            'TRUE_COST_USD': 'sum'
        }).reset_index()
        wh_stats.columns = ['warehouse', 'avg_dur',
                            'max_dur', 'query_count', 'total_cost']

        for _, row in wh_stats.iterrows():
            current_size = self._detect_size(row['warehouse'])

            # SIGNAL 1: High-tier warehouse running micro-tasks (The 'Ferrari in Traffic' case)
            if current_size in ['LARGE', 'X-LARGE', '2X-LARGE'] and row['avg_dur'] < 10:
                recommendations.append({
                    "warehouse": row['warehouse'],
                    "action": "DOWNSIZE",
                    "suggested_size": self._get_smaller_size(current_size),
                    "reason": "High-powered warehouse used for sub-10s queries.",
                    "potential_savings_pct": 50.0
                })

            # SIGNAL 2: Low Volume / High Cost (The 'Idle Burner' case)
            # If total spend is high but throughput is nearly zero
            if row['query_count'] < 5 and row['total_cost'] > 20:
                recommendations.append({
                    "warehouse": row['warehouse'],
                    "action": "DOWNSIZE",
                    "suggested_size": "X-SMALL",
                    "reason": "Idle warehouse cost exceeds processing value. Suggest X-SMALL with Auto-Suspend.",
                    "potential_savings_pct": 75.0
                })
        return recommendations

    def _detect_size(self, name):
        """Heuristic to find WH size from string name."""
        name_upper = name.upper()
        for size in reversed(list(self.WH_SIZE_MAP.keys())):
            if size in name_upper:
                return size
        return "MEDIUM"

    def _get_smaller_size(self, current):
        """Steps down the warehouse size by one tier."""
        sizes = list(self.WH_SIZE_MAP.keys())
        return sizes[max(0, sizes.index(current) - 1)]
