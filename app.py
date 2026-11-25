# Streamlit dashboard (explainable match cards + Apply status tracker)
import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from config.settings import get_settings

st.set_page_config(
    page_title="AI Job Intelligence Dashboard",
    page_icon="🎯",
    layout="wide",
)

DB_PATH = Path("data/jobs.db")
DEFAULT_THRESHOLD = getattr(get_settings(), "MIN_MATCH_SCORE", 75)


def parse_skills(raw_val) -> list:
    """Safely parses JSON-encoded skill lists stored in SQLite."""
    if not raw_val:
        return []
    if isinstance(raw_val, list):
        return raw_val
    try:
        parsed = json.loads(raw_val)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return [s.strip() for s in str(raw_val).split(",") if s.strip()]


@st.cache_data(ttl=60)
def load_jobs() -> pd.DataFrame:
    """Loads all scored jobs from SQLite, ordered by highest match score."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query("SELECT * FROM jobs ORDER BY match_score DESC, collected_at DESC", conn)
    finally:
        conn.close()
    return df


def score_badge(score: int) -> str:
    if score >= 85:
        return f"🟢 **{score}/100**"
    if score >= 70:
        return f"🟡 **{score}/100**"
    return f"🔴 **{score}/100**"


# --- Header ---
st.title("🎯 AI Job Intelligence Dashboard")
st.caption("Automated India Tech & AI/ML Job Matcher — Powered by 3-Tier LLM Fallback")

df = load_jobs()

if df.empty:
    st.warning("No jobs found in `data/jobs.db`. Run `python pipeline.py` first to populate the database.")
    st.stop()

# --- Sidebar Filters ---
st.sidebar.header("Filters")

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

min_score = st.sidebar.slider(
    "Minimum Match Score",
    min_value=0,
    max_value=100,
    value=int(DEFAULT_THRESHOLD),
    step=5,
)

fresher_only = st.sidebar.checkbox("Fresher-friendly only (0–2 yrs)", value=True)

role_options = sorted(df["role_family"].dropna().unique().tolist()) if "role_family" in df.columns else []
selected_roles = st.sidebar.multiselect("Role Family", options=role_options, default=role_options)

source_options = sorted(df["source"].dropna().unique().tolist()) if "source" in df.columns else []
selected_sources = st.sidebar.multiselect("Source", options=source_options, default=source_options)

search_query = st.sidebar.text_input("Search title or company", placeholder="e.g., CGI, Generative AI...")

# --- Apply Filters ---
filtered = df[df["match_score"] >= min_score].copy()

if fresher_only and "is_fresher_friendly" in filtered.columns:
    filtered = filtered[filtered["is_fresher_friendly"].astype(bool)]

if selected_roles and "role_family" in filtered.columns:
    filtered = filtered[filtered["role_family"].isin(selected_roles)]

if selected_sources and "source" in filtered.columns:
    filtered = filtered[filtered["source"].isin(selected_sources)]

if search_query.strip():
    q = search_query.strip().lower()
    filtered = filtered[
        filtered["title"].str.lower().str.contains(q, na=False)
        | filtered["company_canonical"].str.lower().str.contains(q, na=False)
    ]

# --- Top KPI Metrics ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Saved Jobs", len(df))
col2.metric(f"Matches (≥ {min_score}%)", len(filtered))
col3.metric(
    "Fresher-Friendly",
    int(filtered["is_fresher_friendly"].astype(bool).sum()) if "is_fresher_friendly" in filtered.columns else 0,
)
col4.metric("Avg Score (Filtered)", f"{filtered['match_score'].mean():.1f}" if not filtered.empty else "—")

st.divider()

# --- Job Cards ---
if filtered.empty:
    st.info("No jobs match your current filters. Try lowering the Minimum Match Score in the sidebar.")
else:
    for _, row in filtered.iterrows():
        with st.container(border=True):
            top_left, top_right = st.columns([4, 1])

            with top_left:
                st.subheader(f"{row['title']} — {row['company_canonical']}")
                location_str = row.get("location") or "India / Not specified"
                remote_tag = " | 🌐 Remote" if row.get("is_remote") else ""
                fresher_tag = " | 🎓 Fresher-Friendly" if row.get("is_fresher_friendly") else ""
                role_tag = f" | 🏷️ {row['role_family']}" if row.get("role_family") else ""
                st.caption(f"📍 {location_str}{remote_tag}{fresher_tag}{role_tag} | Source: `{row.get('source', 'N/A')}`")

            with top_right:
                st.markdown(score_badge(int(row["match_score"])))
                st.link_button("Apply Now ↗", url=row["url"], use_container_width=True)

            if row.get("reasoning"):
                st.write(row["reasoning"])

            matching = parse_skills(row.get("matching_skills"))
            missing = parse_skills(row.get("missing_skills"))

            s_col1, s_col2 = st.columns(2)
            with s_col1:
                st.markdown(f"**✅ Matching Skills:** {', '.join(matching) if matching else '—'}")
            with s_col2:
                st.markdown(f"**⚠️ Missing Skills:** {', '.join(missing) if missing else 'None'}")

            provider = row.get("llm_provider_used", "Unknown")
            st.caption(f"Scored by: {provider}")