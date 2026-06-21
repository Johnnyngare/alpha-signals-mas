import sqlite3
import pandas as pd
import streamlit as st
from pathlib import Path

# FIX 1: st.set_page_config MUST be the absolute first execution command in the script
st.set_page_config(
    page_title="Alpha Signals Intelligence Dashboard",
    page_icon="📊",
    layout="wide",
)

SCHEMA_VERSION: str = "1.0.0"
"""
Current database schema version.

MIGRATION POLICY (until Alembic is introduced):
------------------------------------------------
When a schema change is required:
1. Increment SCHEMA_VERSION following semver
2. Add the migration SQL as a separate function named migrate_X_Y_Z()
"""

DB_PATH = "data/alpha_signals.db"

st.markdown("""
    <style>
    .main { background-color: #0F172A; }
    .block-container { padding-top: 2rem; }
    h1, h2, h3 { color: #38BDF8; }
    .metric-label { color: #94A3B8; }
    </style>
""", unsafe_allow_html=True)

st.title("ALPHA SIGNALS INTELLIGENCE SYSTEM")
st.caption("Operational Dashboard — Read Only")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_recent_runs(limit: int = 30) -> pd.DataFrame:
    try:
        conn = get_connection()
        df = pd.read_sql_query(
            """
            SELECT
                run_id,
                executed_at,
                fixtures_scanned,
                records_ingested,
                anomalies_found,
                arb_opportunities,
                kelly_suggestions,
                confidence_score,
                broadcast_result,
                execution_secs,
                analysis_mode,
                retry_count
            FROM pipeline_runs
            ORDER BY executed_at DESC -- FIX 2: Corrected column from 'created_at' to 'executed_at'
            LIMIT ?
            """,
            conn,
            params=(limit,)
        )
        conn.close()
        return df
    except Exception as e:
        st.error(f"Could not load pipeline runs: {e}")
        return pd.DataFrame()


def load_flagged_fixtures(limit: int = 15) -> pd.DataFrame:
    try:
        conn = get_connection()
        df = pd.read_sql_query(
            """
            SELECT
                fixture,
                COUNT(*)                 AS times_flagged,
                ROUND(AVG(discrepancy_pct), 2) AS avg_discrepancy_pct,
                ROUND(MAX(discrepancy_pct), 2) AS max_discrepancy_pct,
                SUM(has_kelly)           AS kelly_opportunities
            FROM market_anomalies
            GROUP BY fixture
            ORDER BY times_flagged DESC
            LIMIT ?
            """,
            conn,
            params=(limit,)
        )
        conn.close()
        return df
    except Exception as e:
        st.error(f"Could not load anomaly data: {e}")
        return pd.DataFrame()


def load_anomaly_trend() -> pd.DataFrame:
    try:
        conn = get_connection()
        df = pd.read_sql_query(
            """
            SELECT
                DATE(executed_at) AS run_date,
                AVG(anomalies_found) AS avg_anomalies,
                AVG(confidence_score) AS avg_confidence,
                COUNT(*) AS runs
            FROM pipeline_runs
            GROUP BY DATE(executed_at)
            ORDER BY run_date ASC
            """,
            conn,
        )
        conn.close()
        return df
    except Exception as e:
        st.error(f"Could not load trend data: {e}")
        return pd.DataFrame()


if not Path(DB_PATH).exists():
    st.warning(
        "Database not found at data/alpha_signals.db. "
        "Run python run.py at least once to initialize it."
    )
    st.stop()

runs_df = load_recent_runs()

if runs_df.empty:
    st.info("No pipeline runs recorded yet. Run python run.py to generate data.")
    st.stop()

st.subheader("Pipeline Overview")

col1, col2, col3, col4, col5 = st.columns(5)

total_runs       = len(runs_df)
avg_anomalies    = round(runs_df["anomalies_found"].mean(), 1)
avg_confidence   = round(runs_df["confidence_score"].mean() * 100, 2)
total_arbs       = int(runs_df["arb_opportunities"].sum())
successful_runs  = len(runs_df[runs_df["broadcast_result"] == "success"])

col1.metric("Total Runs",         total_runs)
col2.metric("Avg Anomalies/Run",  avg_anomalies)
col3.metric("Avg Confidence",     f"{avg_confidence}%")
col4.metric("Arb Windows Found",  total_arbs)
col5.metric("Successful Broadcasts", successful_runs)

st.divider()

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Anomaly Trend by Day")
    trend_df = load_anomaly_trend()
    if not trend_df.empty:
        st.line_chart(
            trend_df.set_index("run_date")[["avg_anomalies"]],
            use_container_width=True,
        )

with col_right:
    st.subheader("Most Flagged Fixtures")
    fixtures_df = load_flagged_fixtures()
    if not fixtures_df.empty:
        st.bar_chart(
            fixtures_df.set_index("fixture")["times_flagged"],
            use_container_width=True,
        )

st.divider()

st.subheader("Recent Pipeline Runs")
st.dataframe(
    runs_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "confidence_score": st.column_config.ProgressColumn(
            "Confidence",
            min_value=0,
            max_value=1,
            format="%.2f",
        ),
        "broadcast_result": st.column_config.TextColumn("Broadcast"),
        "execution_secs":   st.column_config.NumberColumn("Secs", format="%.2f"),
    }
)

st.divider()

st.subheader("Anomaly Intelligence — Most Flagged Markets")
fixtures_df = load_flagged_fixtures(20)
if not fixtures_df.empty:
    st.dataframe(
        fixtures_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "avg_discrepancy_pct": st.column_config.NumberColumn(
                "Avg Discrepancy %", format="%.2f"
            ),
            "max_discrepancy_pct": st.column_config.NumberColumn(
                "Max Discrepancy %", format="%.2f"
            ),
        }
    )

st.caption(
    "Alpha Signals MAS — Intelligence Dashboard v1.0 | "
    "Data source: data/alpha_signals.db | Read-only view"
)