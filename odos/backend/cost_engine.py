import pandas as pd

from odos.backend.config_loader import CONFIG
from odos.backend.db import get_db_engine


class CostEngine:
    def __init__(self, engine=None):
        self.engine = engine if engine else get_db_engine()
        self.budget_cap = CONFIG.get('app', {}).get('budget_cap', 2000)

    def get_financial_summary(self):
        try:
            df_base = pd.read_sql(
                "SELECT COALESCE(SUM(avg_cost_usd), 0) as total_baseline_cost FROM query_fingerprints", self.engine)
            daily_base = float(df_base.iloc[0]['total_baseline_cost'])

            query_waste = "SELECT COALESCE(SUM(waste_usd), 0) / NULLIF(COUNT(DISTINCT CAST(timestamp AS DATE)), 0) as daily_waste FROM audit_events"
            df_waste = pd.read_sql(query_waste, self.engine)
            daily_waste = float(
                df_waste.iloc[0]['daily_waste']) if not df_waste.empty and df_waste.iloc[0]['daily_waste'] is not None else 0.0

            annual_burn = (daily_base + daily_waste) * 365
            annual_waste = daily_waste * 365
            efficiency_score = max(
                0, 100 - (annual_waste / annual_burn * 100)) if annual_burn > 0 else 100.0

            return {
                "daily_base": daily_base, "daily_waste": daily_waste,
                "annual_burn": annual_burn, "annual_waste": annual_waste,
                "efficiency_score": int(efficiency_score), "budget_cap": self.budget_cap
            }
        except Exception as e:
            return {"daily_base": 0.0, "daily_waste": 0.0, "efficiency_score": 0, "budget_cap": self.budget_cap}

    def get_anomalies(self, limit=200):
        query = f"SELECT task_id, waste_usd, severity, timestamp FROM audit_events ORDER BY timestamp DESC LIMIT {limit}"
        return pd.read_sql(query, self.engine)

    def close(self):
        pass
