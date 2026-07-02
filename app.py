import streamlit as st
import pandas as pd
import plotly.express as px
from query_engine import (
    generate_and_run_sql, analyze_results, run_query,
    get_recent_query_log, compute_risk_signals
)

st.set_page_config(page_title="Meezan AI Analyst", layout="wide")

# ---------------------------------------------------------------------------
# DESIGN SYSTEM
# A small, deliberate token set (colors/fonts) instead of default Streamlit
# styling. Everything below maps to these variables so the whole look can be
# retuned from one place. Palette: deep navy for structure/headers, a single
# muted green accent (nods to Meezan's brand green, used sparingly), warm
# grey neutrals, and desaturated status colors for risk severity - nothing
# neon, nothing playful, in line with a "clean corporate/banking" brief.
# ---------------------------------------------------------------------------
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --navy-900: #0F2A43;
    --navy-800: #15334F;
    --navy-700: #1B3A5C;
    --accent:   #2E7D5B;
    --bg:       #F5F6F8;
    --card:     #FFFFFF;
    --border:   #E2E5EA;
    --text:     #1A1F29;
    --text-muted: #5B6472;
    --danger:     #B3261E;
    --danger-bg:  #FBEAE8;
    --warning:    #8A6116;
    --warning-bg: #FBF1E1;
    --info-bg:    #EAF0F6;
    --neutral-bg: #F0F1F3;
}

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
code, pre, .mono { font-family: 'JetBrains Mono', monospace; }

/* Hide the default Streamlit chrome (menu/footer) for a cleaner shell.
   Re-enable by deleting this block if you want the menu back. */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

[data-testid="stAppViewContainer"] { background: var(--bg); }
[data-testid="stHeader"] { background: transparent; }

/* Top header band */
.app-header {
    background: var(--navy-900);
    margin: -1rem -1rem 1.5rem -1rem;
    padding: 1.6rem 2.2rem;
    border-radius: 0 0 10px 10px;
}
.app-header h1 {
    color: #FFFFFF;
    font-size: 1.5rem;
    font-weight: 600;
    margin: 0;
    letter-spacing: 0.01em;
}
.app-header p {
    color: #AEBFD2;
    font-size: 0.88rem;
    margin: 0.25rem 0 0 0;
}

/* Section eyebrow labels - small caps grey label above each section title */
.eyebrow {
    color: var(--text-muted);
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 0.2rem;
}
.section-title {
    color: var(--navy-900);
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0 0 0.8rem 0;
}

/* Generic card wrapper */
.card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.1rem 1.3rem;
    margin-bottom: 1.2rem;
}

/* KPI cards */
.kpi-row { display: flex; gap: 0.9rem; margin-bottom: 1.2rem; flex-wrap: wrap; }
.kpi-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-left: 3px solid var(--navy-700);
    border-radius: 6px;
    padding: 0.7rem 1rem;
    flex: 1;
    min-width: 160px;
}
.kpi-label {
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}
.kpi-value {
    color: var(--navy-900);
    font-size: 1.35rem;
    font-weight: 600;
    margin-top: 0.15rem;
}

/* Risk signal chips */
.signal-chip {
    display: flex;
    align-items: flex-start;
    gap: 0.55rem;
    border-radius: 6px;
    padding: 0.55rem 0.75rem;
    margin-bottom: 0.5rem;
    font-size: 0.85rem;
    line-height: 1.35;
}
.signal-chip .dot {
    width: 7px; height: 7px; border-radius: 50%;
    margin-top: 0.35rem; flex-shrink: 0;
}
.signal-high    { background: var(--danger-bg);  color: var(--danger); }
.signal-high .dot     { background: var(--danger); }
.signal-medium  { background: var(--warning-bg); color: var(--warning); }
.signal-medium .dot   { background: var(--warning); }
.signal-info    { background: var(--info-bg);    color: var(--navy-800); }
.signal-info .dot     { background: var(--navy-700); }
.signal-neutral { background: var(--neutral-bg); color: var(--text-muted); }
.signal-neutral .dot  { background: var(--text-muted); }

/* Analyst note block */
.analyst-note {
    border-left: 3px solid var(--accent);
    background: #F3F8F5;
    color: var(--text);
    padding: 0.85rem 1rem;
    border-radius: 6px;
    font-size: 0.92rem;
    line-height: 1.55;
    white-space: pre-wrap;
}

/* Inputs and buttons */
div[data-testid="stTextInput"] input {
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.55rem 0.75rem;
}
div[data-testid="stTextInput"] input:focus {
    border-color: var(--navy-700);
    box-shadow: 0 0 0 1px var(--navy-700);
}
button[kind="primary"], div[data-testid="stButton"] button {
    background: var(--navy-900);
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    font-weight: 500;
    padding: 0.5rem 1.1rem;
}
button[kind="primary"]:hover, div[data-testid="stButton"] button:hover {
    background: var(--navy-700);
    color: #FFFFFF;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: var(--navy-900);
}
section[data-testid="stSidebar"] * { color: #D7E0EA; }
section[data-testid="stSidebar"] .eyebrow { color: #8CA3BA; }

.log-entry {
    display: flex; align-items: flex-start; gap: 0.5rem;
    font-size: 0.8rem; padding: 0.4rem 0; border-bottom: 1px solid #24405C;
}
.log-entry .dot { width: 6px; height: 6px; border-radius: 50%; margin-top: 0.3rem; flex-shrink: 0; }
.log-dot-success { background: var(--accent); }
.log-dot-failed   { background: #D98C8C; }
.log-dot-rejected { background: #D9B36C; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

st.markdown(
    """
    <div class="app-header">
        <h1>Meezan AI Analyst</h1>
        <p>Branch insights and recommendation engine - ask a question in plain English</p>
    </div>
    """,
    unsafe_allow_html=True
)

# ---------------------------------------------------------------------------
# SESSION STATE
# Streamlit reruns the ENTIRE script top-to-bottom on every button click, so
# results are stashed in session_state to survive the rerun triggered by the
# drill-down button below (see the longer explanation further down).
# ---------------------------------------------------------------------------
if "df" not in st.session_state:
    st.session_state.df = None
if "question" not in st.session_state:
    st.session_state.question = None
if "sql_used" not in st.session_state:
    st.session_state.sql_used = None


def render_severity_chips(signals):
    """Renders a list of (text, severity) tuples as color-coded chips."""
    html = ""
    for text, severity in signals:
        css_class = f"signal-{severity}" if severity in ("high", "medium", "info") else "signal-neutral"
        html += f'<div class="signal-chip {css_class}"><span class="dot"></span><span>{text}</span></div>'
    st.markdown(html, unsafe_allow_html=True)


def render_kpi_row(df):
    """
    Renders a small row of KPI cards summarizing the current result set:
    row count, plus (if present) the sum of the first numeric column and a
    distinct-count of the most relevant identifier column. Keeps the
    dashboard feeling like it's oriented you before you read the table.
    """
    kpis = [("Rows returned", f"{len(df):,}")]

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        primary_numeric = numeric_cols[0]
        total = df[primary_numeric].sum()
        kpis.append((f"Sum of {primary_numeric}", f"{total:,.0f}"))

    for id_col, label in [("account_id", "Distinct accounts"),
                           ("customer_id", "Distinct customers"),
                           ("branch_name", "Distinct branches")]:
        if id_col in df.columns:
            kpis.append((label, f"{df[id_col].nunique():,}"))
            break

    cards_html = '<div class="kpi-row">'
    for label, value in kpis:
        cards_html += (
            f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value">{value}</div></div>'
        )
    cards_html += "</div>"
    st.markdown(cards_html, unsafe_allow_html=True)


def render_chart(df):
    """
    Builds a Plotly chart styled to match the design system, instead of
    Streamlit's default bar chart. Prefers a monthly trend line when a
    transaction date column is present (the most common realistic view for
    banking data); otherwise falls back to a bar chart across a low-
    cardinality categorical column (e.g. branch, account type, segment).
    Returns True if a chart was rendered, False if there wasn't a sensible
    one to draw.
    """
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if not numeric_cols:
        return False
    primary_numeric = numeric_cols[0]

    fig = None
    if "tx_date" in df.columns:
        temp = df.copy()
        temp["tx_date"] = pd.to_datetime(temp["tx_date"], errors="coerce")
        temp = temp.dropna(subset=["tx_date"])
        if not temp.empty:
            monthly = temp.set_index("tx_date").resample("ME")[primary_numeric].sum().reset_index()
            if len(monthly) > 1:
                fig = px.line(monthly, x="tx_date", y=primary_numeric, markers=True)
                fig.update_traces(line_color="#1B3A5C", marker_color="#2E7D5B")

    if fig is None:
        categorical_cols = [
            col for col in df.select_dtypes(exclude="number").columns
            if df[col].nunique() <= 20 and col != "tx_date"
        ]
        if categorical_cols:
            group_col = categorical_cols[0]
            grouped = (
                df.groupby(group_col)[primary_numeric].sum()
                .reset_index().sort_values(primary_numeric, ascending=False)
            )
            fig = px.bar(grouped, x=group_col, y=primary_numeric)
            fig.update_traces(marker_color="#1B3A5C")

    if fig is None:
        return False

    fig.update_layout(
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        font_family="Inter",
        font_color="#5B6472",
        margin=dict(l=10, r=10, t=10, b=10),
        height=280,
    )
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor="#E2E5EA", title=None)
    st.plotly_chart(fig, use_container_width=True)
    return True


# ---------------------------------------------------------------------------
# SIDEBAR: recent query audit log
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="eyebrow">Audit log</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title" style="color:#FFFFFF;">Recent queries</div>', unsafe_allow_html=True)

    log_df = get_recent_query_log(10)
    if not log_df.empty:
        entries_html = ""
        for _, row in log_df.iterrows():
            dot_class = {
                "success": "log-dot-success",
                "failed": "log-dot-failed",
                "rejected": "log-dot-rejected",
            }.get(row["status"], "log-dot-failed")
            entries_html += (
                f'<div class="log-entry"><span class="dot {dot_class}"></span>'
                f'<span>{row["user_question"]}</span></div>'
            )
        st.markdown(entries_html, unsafe_allow_html=True)
    else:
        st.caption("No queries yet.")

# ---------------------------------------------------------------------------
# 1. INPUT SECTION
# ---------------------------------------------------------------------------
input_col, button_col = st.columns([5, 1])
with input_col:
    question = st.text_input(
        "Ask a question",
        placeholder="e.g. Which branches hold the most SME deposits?",
        label_visibility="collapsed",
    )
with button_col:
    run_clicked = st.button("Run analysis", use_container_width=True)

if run_clicked:
    with st.spinner("Running analysis..."):
        df, sql_used, error_message = generate_and_run_sql(question)
        st.session_state.df = df
        st.session_state.question = question
        st.session_state.sql_used = sql_used

        if df is None:
            st.error(f"Query failed after retries. Last error: {error_message}")
        elif df.empty:
            st.warning("The query ran successfully but returned no rows. Try rephrasing your question.")

# ---------------------------------------------------------------------------
# 2. RESULTS SECTION (reads from session_state so it survives reruns)
# ---------------------------------------------------------------------------
df = st.session_state.df
question = st.session_state.question

if df is not None and not df.empty:

    render_kpi_row(df)

    st.markdown('<div class="eyebrow">Query result</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Data summary</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("View generated SQL"):
        st.code(st.session_state.sql_used, language="sql")

    chart_col, panel_col = st.columns([3, 2])

    with chart_col:
        st.markdown('<div class="eyebrow">Visual</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Trend / distribution</div>', unsafe_allow_html=True)
        st.markdown('<div class="card">', unsafe_allow_html=True)
        chart_rendered = render_chart(df)
        if not chart_rendered:
            st.caption("No chartable numeric/categorical combination in this result.")
        st.markdown("</div>", unsafe_allow_html=True)

    with panel_col:
        st.markdown('<div class="eyebrow">Risk & opportunity</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Signals detected</div>', unsafe_allow_html=True)
        st.markdown('<div class="card">', unsafe_allow_html=True)
        signals = compute_risk_signals(df)
        render_severity_chips(signals)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="eyebrow">Narrative</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Analyst note</div>', unsafe_allow_html=True)
    note = analyze_results(question, df)
    st.markdown(f'<div class="analyst-note">{note}</div>', unsafe_allow_html=True)

    # -----------------------------------------------------------------
    # DRILL-DOWN
    # customer_name lives on the `customers` table, not `accounts` (a
    # customer can have more than one account) - so this joins
    # customers -> accounts -> transactions rather than assuming a flat
    # customer_name column exists on accounts/transactions directly. The
    # query is parameterized (params=...) rather than an f-string, so a
    # name containing a quote/apostrophe can't break it or enable
    # injection. Session state keeps this section's data alive across the
    # rerun triggered by clicking "Get transaction history".
    # -----------------------------------------------------------------
    if "customer_name" in df.columns:
        st.markdown('<div class="eyebrow">Detail</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Transaction history lookup</div>', unsafe_allow_html=True)
        st.markdown('<div class="card">', unsafe_allow_html=True)

        selected_user = st.selectbox("Customer", df["customer_name"].unique(), label_visibility="collapsed")

        if st.button("Get transaction history"):
            tx_sql = """
                SELECT t.tx_date, t.tx_type, t.amount, t.channel, a.account_type
                FROM transactions t
                JOIN accounts a ON t.account_id = a.account_id
                JOIN customers c ON a.customer_id = c.customer_id
                WHERE c.customer_name = ?
                ORDER BY t.tx_date DESC
            """
            tx_df = run_query(tx_sql, params=(selected_user,))
            if tx_df is not None and not tx_df.empty:
                st.dataframe(tx_df, use_container_width=True, hide_index=True)
            else:
                st.warning(f"No transaction history found for {selected_user}.")

        st.markdown("</div>", unsafe_allow_html=True)
