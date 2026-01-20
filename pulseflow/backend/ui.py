from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine

# IMPORT THE TESTABLE LOGIC
from pulseflow.backend.reporting import (calculate_efficiency,
                                         generate_pdf_binary)

# --- CONFIGURATION ---
st.set_page_config(page_title="PulseFlow Commander",
                   page_icon="🚀", layout="wide")
engine = create_engine("sqlite:///pulseflow.db")

# --- DATA FETCHING ---


def get_data():
    # 1. Financials
    query_fin = """
    SELECT 
        SUM(f.avg_cost_usd) as daily_baseline,
        (SELECT SUM(waste_usd) / NULLIF(COUNT(DISTINCT date(timestamp)), 0) FROM audit_events) as daily_waste
    FROM query_fingerprints f
    """
    try:
        fin = pd.read_sql(query_fin, engine).iloc[0]
        base = fin['daily_baseline'] or 0.0
        waste = fin['daily_waste'] or 0.0
    except:
        base, waste = 0.0, 0.0

    # 2. Zombies
    query_zom = "SELECT task_id, waste_usd, severity, timestamp FROM audit_events ORDER BY timestamp DESC"
    zombies = pd.read_sql(query_zom, engine)

    # 3. Cost Centers (Simulated)
    if not zombies.empty:
        zombies['Cost Center'] = zombies['task_id'].apply(
            lambda x: 'Marketing' if 'mktg' in x else ('Engineering' if 'load' in x else 'Unassigned'))
    else:
        zombies['Cost Center'] = []

    return base, waste, zombies


# --- SIDEBAR SETTINGS ---
st.sidebar.title("🛠 Commander Settings")
monthly_budget = st.sidebar.number_input(
    "Monthly Budget Cap ($)", value=2000, step=100)
project_name = st.sidebar.text_input(
    "Project / Client Name", value="Internal Audit")
st.sidebar.markdown("---")

# Global Calculations
daily_base, daily_waste, df_zombies = get_data()
annual_burn = (daily_base + daily_waste) * 365
annual_waste = daily_waste * 365
mtd_spend = (daily_base + daily_waste) * 30 * \
    0.65  # Simulating 20th of the month

# USE IMPORTED LOGIC
efficiency_score = calculate_efficiency(annual_burn, annual_waste)

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 Financial Pulse", "🐋 Whale Hunter", "🧪 What-If Simulator", "📑 Reporting"])

# --- TAB 1: FINANCIAL PULSE ---
with tab1:
    st.header("Financial Pulse & Budget Pacing")
    c1, c2 = st.columns([2, 1])
    with c1:
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=mtd_spend,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': "Month-to-Date Spend ($)"},
            delta={'reference': monthly_budget,
                   'increasing': {'color': "red"}},
            gauge={
                'axis': {'range': [None, monthly_budget * 1.2]},
                'bar': {'color': "#2E86C1"},
                'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': monthly_budget},
                'steps': [{'range': [0, monthly_budget * 0.8], 'color': "#D4E6F1"},
                          {'range': [monthly_budget * 0.8, monthly_budget], 'color': "#F9E79F"}]
            }))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.subheader("Pacing Alert")
        burn_rate = (mtd_spend / monthly_budget) * 100
        if burn_rate > 90:
            st.error(f"🔥 Critical: {burn_rate:.1f}% of budget used!")
        elif burn_rate > 70:
            st.warning(f"⚠️ Warning: {burn_rate:.1f}% of budget used.")
        else:
            st.success(f"✅ Healthy: {burn_rate:.1f}% of budget used.")
        st.metric("Projected Month End", f"${(mtd_spend / 0.65):,.0f}",
                  delta=f"{monthly_budget - (mtd_spend/0.65):.0f} vs Cap")

# --- TAB 2: WHALE HUNTER ---
with tab2:
    st.header("🐋 The Whale Hunter")
    c_pie, c_list = st.columns([1, 2])
    with c_pie:
        if not df_zombies.empty:
            spend = df_zombies.groupby("Cost Center")[
                'waste_usd'].sum().reset_index()
            st.plotly_chart(px.pie(spend, values='waste_usd', names='Cost Center',
                                   title="Waste by Dept"), use_container_width=True)
    with c_list:
        st.subheader("🏆 Top Spenders")
        if not df_zombies.empty:
            st.dataframe(df_zombies.groupby('task_id')['waste_usd'].sum().sort_values(
                ascending=False).head(5), use_container_width=True)

# --- TAB 3: WHAT-IF SIMULATOR ---
with tab3:
    st.header("🧪 Infrastructure Simulator")
    c_sim1, c_sim2 = st.columns(2)
    with c_sim1:
        wh_size = st.select_slider("Marketing Warehouse", options=[
                                   "XS", "S", "M", "L", "XL", "2XL"], value="L")
        hours = st.slider("Daily Runtime (Hours)", 1, 24, 8)
    credits = {"XS": 1, "S": 2, "M": 4, "L": 8, "XL": 16, "2XL": 32}
    base_cost = credits["L"] * 8 * 3.00 * 365
    sim_cost = credits[wh_size] * hours * 3.00 * 365
    with c_sim2:
        st.metric("Annual Cost (Simulated)",
                  f"${sim_cost:,.0f}", delta=f"${base_cost - sim_cost:,.0f} Savings")

# --- TAB 4: REPORTING ---
with tab4:
    st.header("📑 Executive Reporting")
    col_controls, col_preview = st.columns([1, 2])

    with col_controls:
        st.info("Review the data on the right before exporting.")
        st.markdown("### Report Settings")
        include_zombies = st.checkbox("Include Top 5 Anomalies", value=True)
        include_recs = st.checkbox("Include Recommendations", value=True)

        st.markdown("---")

        metrics_data = {
            "burn": annual_burn,
            "waste": annual_waste,
            "budget": monthly_budget,
            "efficiency": int(efficiency_score)
        }

        # USE IMPORTED LOGIC
        pdf_file = generate_pdf_binary(metrics_data, df_zombies, project_name)

        st.download_button(
            label="📄 Export to PDF",
            data=pdf_file,
            file_name=f"PulseFlow_Report_{datetime.now().strftime('%Y-%m-%d')}.pdf",
            mime="application/pdf",
            type="primary"
        )

    with col_preview:
        with st.container(border=True):
            st.markdown(f"## Weekly Cost Report: {project_name}")
            st.caption(
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            st.divider()

            st.markdown("### 1. Executive Financial Summary")
            p1, p2 = st.columns(2)
            p1.metric("Projected Annual Burn", f"${annual_burn:,.2f}")
            p1.metric("Budget Cap", f"${monthly_budget:,.2f}")
            p2.metric("Avoidable Waste",
                      f"${annual_waste:,.2f}", delta_color="inverse")
            p2.metric("Efficiency Score", f"{efficiency_score:.1f}%")

            if include_zombies and not df_zombies.empty:
                st.markdown("### 2. Top 5 Cost Anomalies (Action Required)")
                st.dataframe(
                    df_zombies.head(5)[['task_id', 'severity', 'waste_usd']],
                    hide_index=True,
                    use_container_width=True
                )

            if include_recs:
                st.markdown("### Recommendation")
                st.success(
                    "Review the high-severity anomalies. Downsizing warehouses for the listed tasks could save approx 15-20% of the projected waste.")
