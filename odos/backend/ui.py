import os
import time

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph

from odos.backend.config_loader import CONFIG
from odos.backend.cost_engine import CostEngine
from odos.backend.db import get_db_engine as _get_backend_engine
from odos.backend.reporting import calculate_efficiency, generate_pdf_binary
from odos.backend.storage_advisor import StorageAdvisor
from odos.backend.surgeon import Surgeon

# --- CONFIG & BRANDING ---
COMPANY_NAME = CONFIG['project'].get('company_name', "Prowess Pictures")
PROJECT_NAME = "Odos Data Engineering Operating System"

st.set_page_config(
    page_title=f"{COMPANY_NAME} | {PROJECT_NAME}", page_icon="📡", layout="wide")

# --- AUTH & DB ---


def check_authentication():
    if not CONFIG.get('security', {}).get('auth_enabled', False):
        return True
    if st.session_state.get("authenticated", False):
        return True
    st.markdown(f"## 🔒 {COMPANY_NAME} Control Plane")
    with st.form("login_form"):
        u, p = st.text_input("Username"), st.text_input(
            "Password", type="password")
        if st.form_submit_button("Login"):
            if u == os.getenv("ODOS_ADMIN_USER", "admin") and p == os.getenv("ODOS_ADMIN_PASSWORD", "admin"):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ Access Denied")
    st.stop()
    return False


@st.cache_resource
def get_db_engine():
    return _get_backend_engine()


@st.cache_data(ttl=60)
def get_pipeline_catalog():
    return pd.read_sql("SELECT DISTINCT ON (pipeline_name) * FROM pipeline_runs ORDER BY pipeline_name, start_time DESC", get_db_engine())


@st.cache_data(ttl=300)
def get_financial_data():
    engine = get_db_engine()
    ce = CostEngine(engine=engine)
    metrics = ce.get_financial_summary()
    zombies = ce.get_anomalies(limit=200)
    return metrics['daily_base'], metrics['daily_waste'], zombies, metrics


@st.cache_data(ttl=600)
def get_sql_info(task_id):
    df = pd.read_sql(
        f"SELECT sql_text, optimized_sql_text, diagnosis_text FROM query_fingerprints WHERE hash_id = '{task_id}'", get_db_engine())
    return df.iloc[0] if not df.empty else None


def analyze_workload(description):
    d = description.lower()
    if "tb" in d or "terabyte" in d:
        return "2XL", 6, "High Volume: >10TB workloads.", 32
    if "stream" in d or "real-time" in d:
        return "XS", 24, "Streaming Pattern: 24/7 ingestion.", 1
    if "dbt" in d:
        return "L", 4, "Transformation: dbt parallel execution.", 8
    return "M", 8, "General Purpose: Standard batch.", 4


@st.cache_data(ttl=600)
def get_cached_impact(pipeline_name):
    query = f"""
        WITH RECURSIVE downstream AS (
            SELECT target_node, 1 as distance, ARRAY[target_node]::text[] as path
            FROM lineage_edges WHERE source_node = '{pipeline_name}'
            UNION ALL
            SELECT e.target_node, d.distance + 1, d.path || e.target_node
            FROM lineage_edges e INNER JOIN downstream d ON e.source_node = d.target_node
            WHERE d.distance < 10 AND NOT (e.target_node = ANY(d.path))
        )
        SELECT d.target_node, n.node_type, n.layer, MIN(d.distance) as depth
        FROM downstream d JOIN lineage_nodes n ON d.target_node = n.node_id
        GROUP BY d.target_node, n.node_type, n.layer ORDER BY depth ASC
    """
    return pd.read_sql(query, get_db_engine())

# --- UI FRAGMENTS ---


@st.fragment
def render_pipeline_card(row):
    pid = row['pipeline_name']
    if f"exp_{pid}" not in st.session_state:
        st.session_state[f"exp_{pid}"] = False
    icon = "❌" if row['status'] == 'FAILED' else "✅"
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
        with c1:
            st.markdown(f"### {icon} {pid}")
            st.caption(
                f"Last Run: {row['start_time'].strftime('%Y-%m-%d %H:%M')}")
        with c2:
            st.metric("Latency", f"{row['duration_sec']:.1f}s")
        with c3:
            st.metric("Rows", f"{row['rows_processed']:,}")
        with c4:
            if st.button("✖️ Close" if st.session_state[f"exp_{pid}"] else "🔎 Explore", key=f"btn_{pid}"):
                st.session_state[f"exp_{pid}"] = not st.session_state[f"exp_{pid}"]
                st.rerun(scope="fragment")
        if st.session_state[f"exp_{pid}"]:
            st.divider()
            ca, cb = st.columns(2)
            with ca:
                if row['status'] == 'FAILED':
                    st.error(f"**Error:** {row['error_message']}")
                else:
                    st.success("Health: System nominal.")
            with cb:
                st.dataframe(get_cached_impact(pid), column_config={"target_node": "Affected Asset", "depth": st.column_config.NumberColumn(
                    "Steps", format="%d 🕸️")}, hide_index=True, width="stretch")


@st.fragment
def render_whale_card(z_row):
    tid = z_row['task_id']
    if f"z_exp_{tid}" not in st.session_state:
        st.session_state[f"z_exp_{tid}"] = False
    with st.container(border=True):
        zc1, zc2, zc3 = st.columns([3, 1, 1])
        with zc1:
            st.markdown(
                f"#### {'🔴' if z_row['severity'] == 'HIGH' else '🟡'} {tid}")
        with zc2:
            st.metric("Waste", f"${z_row['waste_usd']:.2f}")
        with zc3:
            if st.button("✖️ Close" if st.session_state[f"z_exp_{tid}"] else "🛠️ Inspect", key=f"zbtn_{tid}"):
                st.session_state[f"z_exp_{tid}"] = not st.session_state[f"z_exp_{tid}"]
                st.rerun(scope="fragment")
        if st.session_state[f"z_exp_{tid}"]:
            sql = get_sql_info(tid)
            if sql is not None:
                st.code(sql['sql_text'], language="sql")
                if sql['optimized_sql_text']:
                    st.info(f"💡 {sql['diagnosis_text']}")
                    st.code(sql['optimized_sql_text'], language="sql")


# --- MAIN EXECUTION ---
if check_authentication():
    base, waste, zombies, raw_metrics = get_financial_data()
    burn, waste_ann, mtd = (base + waste) * 365, waste * \
        365, (base + waste) * 30 * 0.65
    eff = calculate_efficiency(burn, waste_ann)
    budget = int(CONFIG['app'].get('budget_cap', 2000))

    st.title(f"📡 {COMPANY_NAME}: {PROJECT_NAME}")
    tabs = st.tabs(["🚦 Command Center", "📊 Financial Pulse",
                   "🐋 Whale Hunter", "🧪 Simulator", "🗄️ Storage Ops", "📑 Reporting"])

    with tabs[0]:
        df = get_pipeline_catalog()
        for _, r in df.head(10).iterrows():
            render_pipeline_card(r)

    with tabs[1]:  # Gauge restored to your requested layout
        fig = go.Figure(go.Indicator(mode="gauge+number+delta", value=mtd, delta={'reference': budget},
                                     gauge={'axis': {'range': [None, budget * 1.5]}, 'bar': {'color': "#1C83E1"},
                                            'threshold': {'line': {'color': "red", 'width': 4}, 'value': budget}}))
        st.plotly_chart(fig, use_container_width=True)

    with tabs[2]:
        df_z = zombies.groupby('task_id').agg({'waste_usd': 'sum', 'timestamp': 'max', 'severity': lambda x: 'HIGH' if 'HIGH' in list(
            x) else 'LOW'}).sort_values('waste_usd', ascending=False).reset_index()
        for _, r in df_z.head(10).iterrows():
            render_whale_card(r)

    with tabs[3]:
        desc = st.text_area("Workload description:")
        if st.button("🔮 Calculate"):
            sz, hr, rsn, mult = analyze_workload(desc)
            st.info(
                f"**AI Recommendation:** {sz} Warehouse | **Est. Cost:** ${mult * hr * 3.0:,.2f} | **Logic:** {rsn}")

    with tabs[4]:
        ghosts = StorageAdvisor().find_ghost_tables()
        st.metric("Ghost Tables", len(
            ghosts), delta=f"${len(ghosts)*25:,.0f} Waste/mo", delta_color="inverse")
        st.dataframe(ghosts, column_config={"table_name": "Database Object", "size_bytes": st.column_config.NumberColumn(
            "Volume", format="%.2f MB"), "unused_days": st.column_config.NumberColumn("Days Stagnant", format="%d ⏳")}, hide_index=True, width="stretch")

    with tabs[5]:
        st.table(pd.DataFrame({"Metric": ["Annual Burn", "Annual Waste", "Efficiency Score"], "Value": [
                 f"${burn:,.0f}", f"${waste_ann:,.0f}", f"{eff}%"]}))
        if st.button("🚀 Build PDF"):
            pdf = generate_pdf_binary(
                {"burn": burn, "waste": waste_ann, "budget": budget, "efficiency": int(eff)}, zombies, COMPANY_NAME)
            st.download_button("📥 Download", data=pdf,
                               file_name=f"{COMPANY_NAME}_Report.pdf")
