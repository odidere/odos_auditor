import pandas as pd


class EfficiencyAuditor:
    def __init__(self, raw_data):
        self.df = pd.DataFrame(raw_data)

    def generate_zombie_report(self):
        # Default empty report structure
        empty_report = {
            "status": "clean",
            "total_daily_waste_usd": 0.0,
            "projected_annual_waste_usd": 0.0,
            "top_offenders": [],
            "recommendation": "No inefficiencies detected."
        }

        if self.df.empty:
            return empty_report

        # Safety check for required column
        if 'EFFICIENCY_TAG' not in self.df.columns:
            return empty_report

        # Filter for flagged rows
        zombies = self.df[self.df['EFFICIENCY_TAG']
                          == 'POTENTIAL_WASTE'].copy()

        if zombies.empty:
            return empty_report

        # --- CALCULATION LOGIC ---
        # Waste = (60s Minimum - Actual Duration) * Cost Per Second
        zombies['billed_seconds'] = 60.0
        zombies['wasted_seconds'] = zombies['billed_seconds'] - \
            zombies['DURATION_SEC']

        # Derive per-second rate safely
        zombies['implied_rate'] = zombies['TRUE_COST_USD'] / \
            zombies['DURATION_SEC']
        zombies['wasted_usd'] = zombies['wasted_seconds'] * \
            zombies['implied_rate']

        # Group by Task
        report = zombies.groupby(['DAG_ID', 'TASK_ID']).agg({
            'wasted_usd': 'sum',
            'QUERY_ID': 'count'
        }).reset_index()

        report.rename(columns={'QUERY_ID': 'execution_count'}, inplace=True)
        report.sort_values('wasted_usd', ascending=False, inplace=True)

        daily_waste = report['wasted_usd'].sum()

        return {
            "status": "critical" if daily_waste > 50 else "warning",
            "total_daily_waste_usd": round(daily_waste, 2),
            "projected_annual_waste_usd": round(daily_waste * 365, 2),
            "recommendation": "Batch short tasks to reduce warehouse spin-up costs.",
            "top_offenders": report.head(10).to_dict(orient='records')
        }
