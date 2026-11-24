"""Streamlit dashboard. Start with ``odos ui``.

Login: when ``security.auth_enabled`` is true, set ``ODOS_ADMIN_USER`` and
``ODOS_ADMIN_PASSWORD``. There is no default password.
"""
from __future__ import annotations

import hmac
import os

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from odos.backend.cost_engine import CostEngine, suggestion_to_dict
from odos.backend.db import get_engine, init_db
from odos.backend.models import Suggestion
from odos.backend.remediation import ReviewError, approve, reject
from odos.backend.reporting import generate_pdf_binary
from odos.config import section

COMPANY_NAME = section("project").get("company_name", "Odos")
PROJECT_NAME = section("project").get("name", "Odos Auditor")

st.set_page_config(page_title=f"{COMPANY_NAME} | {PROJECT_NAME}", page_icon="📡", layout="wide")


# --- auth -------------------------------------------------------------------
def check_authentication() -> bool:
    if not section("security").get("auth_enabled", True):
        return True
    if st.session_state.get("authenticated"):
        return True
    expected_user = os.getenv("ODOS_ADMIN_USER", "admin")
    expected_password = os.getenv("ODOS_ADMIN_PASSWORD")
    st.markdown(f"## {COMPANY_NAME} control plane")
    if not expected_password:
        st.error("Set ODOS_ADMIN_PASSWORD to enable login, or set security.auth_enabled: false for local demos.")
        st.stop()
    with st.form("login_form"):
        user = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Log in"):
            if hmac.compare_digest(user, expected_user) and hmac.compare_digest(password, expected_password):
                st.session_state["authenticated"] = True
                st.session_state["reviewer"] = user
                st.rerun()
            st.error("Access denied")
    st.stop()
    return False


# --- data -------------------------------------------------------------------
@st.cache_resource
def engine():
    return init_db(get_engine())


@st.cache_data(ttl=60)
def pipeline_catalog() -> pd.DataFrame:
    query = text("""
        SELECT r.* FROM pipeline_runs r
        JOIN (SELECT pipeline_name, MAX(start_time) AS latest FROM pipeline_runs GROUP BY pipeline_name) l
          ON r.pipeline_name = l.pipeline_name AND r.start_time = l.latest
        ORDER BY r.start_time DESC
    """)
    with engine().connect() as conn:
        return pd.read_sql(query, conn)


@st.cache_data(ttl=300)
def lineage_graph() -> nx.DiGraph:
    with engine().connect() as conn:
        edges = conn.execute(text("SELECT source_node, target_node FROM lineage_edges")).all()
    graph = nx.DiGraph()
    graph.add_edges_from((e[0], e[1]) for e in edges)
    return graph


def downstream(pipeline_name: str) -> pd.DataFrame:
    graph = lineage_graph()
    if pipeline_name not in graph:
        return pd.DataFrame(columns=["affected_asset", "steps"])
    depths = nx.single_source_shortest_path_length(graph, pipeline_name, cutoff=10)
    rows = [{"affected_asset": node, "steps": d} for node, d in depths.items() if node != pipeline_name]
    return pd.DataFrame(rows).sort_values("steps") if rows else pd.DataFrame(columns=["affected_asset", "steps"])


@st.cache_data(ttl=120)
def financials():
    ce = CostEngine(engine())
    return ce.get_financial_summary(), pd.DataFrame(ce.get_anomalies(limit=200))


def load_suggestions(status: str | None) -> list[dict]:
    with Session(engine()) as s:
        stmt = select(Suggestion).order_by(Suggestion.created_at.desc()).limit(50)
        if status:
            stmt = stmt.where(Suggestion.status == status)
        return [suggestion_to_dict(x) for x in s.scalars(stmt).all()]


# --- views ------------------------------------------------------------------
def render_pipelines() -> None:
    df = pipeline_catalog()
    if df.empty:
        st.info("No pipeline runs yet. Decorate a pipeline with @track_pipeline to record runs.")
        return
    for _, row in df.head(20).iterrows():
        icon = "❌" if row["status"] == "FAILED" else "✅"
        with st.expander(f"{icon} {row['pipeline_name']} · {row['duration_sec']:.1f}s · "
                         f"{int(row['rows_processed'] or 0):,} rows"):
            if row["status"] == "FAILED":
                st.error(row["error_message"])
            st.dataframe(downstream(row["pipeline_name"]), hide_index=True, width="stretch")


def render_financials(metrics: dict, budget: float) -> None:
    month_to_date = metrics["daily_spend"] * 30
    c1, c2, c3 = st.columns(3)
    c1.metric("Projected monthly spend", f"${month_to_date:,.0f}")
    c2.metric("Flagged excess (annualised)", f"${metrics['annual_waste']:,.0f}")
    c3.metric("Efficiency score", f"{metrics['efficiency_score']}%")
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta", value=month_to_date, delta={"reference": budget},
        gauge={"axis": {"range": [None, budget * 1.5]},
               "threshold": {"line": {"color": "red", "width": 4}, "value": budget}}))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Based on {metrics['days_observed']} day(s) of attributed query cost.")


def render_anomalies(events: pd.DataFrame) -> None:
    if events.empty:
        st.info("No anomalies yet. Run `odos audit` to analyse recent queries.")
        return
    cols = ["timestamp", "severity", "dag_id", "task_id", "cost_usd", "baseline_usd", "ratio", "waste_usd", "fingerprint"]
    st.dataframe(events[[c for c in cols if c in events.columns]], hide_index=True, width="stretch")


def render_suggestions() -> None:
    st.caption("AI suggestions are never executed. Approving records your decision; apply the change yourself.")
    status = st.selectbox("Status", ["PENDING", "INVALID", "FAILED", "APPROVED", "REJECTED"], index=0)
    items = load_suggestions(status)
    if not items:
        st.info(f"No {status.lower()} suggestions.")
        return
    reviewer = st.session_state.get("reviewer") or st.text_input("Your name (recorded with each decision)")
    for item in items:
        title = f"#{item['id']} · {item['strategy'] or 'no strategy'} · est. {item['estimated_savings_pct'] or 0}% saving"
        with st.expander(title):
            st.write(item["diagnosis"] or "")
            left, right = st.columns(2)
            left.markdown("**Original (as sent to the model)**")
            left.code(item["original_sql"] or "", language="sql")
            right.markdown("**Suggested**")
            right.code(item["suggested_sql"] or "", language="sql")
            if item["validation_notes"]:
                st.warning(item["validation_notes"])
            st.caption(f"{item['provider'] or '-'} / {item['model'] or '-'} · {item['latency_ms'] or '-'} ms")
            if item["status"] == "PENDING":
                note = st.text_input("Note", key=f"note_{item['id']}")
                a, r = st.columns(2)
                for column, label, action in ((a, "Approve", approve), (r, "Reject", reject)):
                    if column.button(label, key=f"{label}_{item['id']}", disabled=not reviewer):
                        try:
                            with Session(engine()) as s:
                                action(s, item["id"], reviewer, note or None)
                            st.success(f"{label}d.")
                            st.rerun()
                        except ReviewError as exc:
                            st.error(str(exc))


def render_storage() -> None:
    if not os.getenv("SNOWFLAKE_ACCOUNT"):
        st.info("Set SNOWFLAKE_* environment variables to scan storage.")
        return
    from odos.backend.storage_advisor import StorageAdvisor

    if st.button("Scan for unused tables"):
        try:
            ghosts = StorageAdvisor().find_ghost_tables()
            st.metric("Unused large tables", len(ghosts))
            st.dataframe(ghosts, hide_index=True, width="stretch")
        except Exception as exc:
            st.error(f"Storage scan failed: {exc}")


def main() -> None:
    if not check_authentication():
        return
    metrics, events = financials()
    budget = float(section("app").get("budget_cap", 2000))
    st.title(f"📡 {COMPANY_NAME}: {PROJECT_NAME}")
    tabs = st.tabs(["Pipelines", "Spend", "Anomalies", "Suggestions", "Storage", "Report"])
    with tabs[0]:
        render_pipelines()
    with tabs[1]:
        render_financials(metrics, budget)
    with tabs[2]:
        render_anomalies(events)
    with tabs[3]:
        render_suggestions()
    with tabs[4]:
        render_storage()
    with tabs[5]:
        if st.button("Build PDF report"):
            pdf = generate_pdf_binary({"burn": metrics["annual_burn"], "waste": metrics["annual_waste"],
                                       "budget": budget, "efficiency": metrics["efficiency_score"]},
                                      events.to_dict(orient="records"), COMPANY_NAME)
            st.download_button("Download", data=pdf, file_name=f"{COMPANY_NAME}_cost_report.pdf")


main()
