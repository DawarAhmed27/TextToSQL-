import sqlite3
import re
import datetime
import pandas as pd
from openai import OpenAI

client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

DB_PATH = "bank_data.db"

# ---------------------------------------------------------------------------
# CONFIG / TUNABLE CONSTANTS
# Keeping these at the top makes it easy to tune behaviour without hunting
# through function bodies.
# ---------------------------------------------------------------------------

MAX_SQL_RETRIES = 2          # how many times we let the LLM try to fix a broken query
DEFAULT_ROW_LIMIT = 500      # safety cap so a bad query can't dump a huge table into the UI

# Keywords that should NEVER appear in an LLM-generated query. Even though we
# check the query starts with SELECT, a malicious/confused model could still
# smuggle in a subquery or stacked statement using these.
FORBIDDEN_KEYWORDS = [
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "ATTACH",
    "PRAGMA", "CREATE", "REPLACE", "VACUUM", "--", "/*"
]

# Risk-signal thresholds (all in PKR, tuned to the synthetic dataset in
# generate_data.py - adjust these if you plug in your own data).
DORMANCY_DAYS = 90                  # no activity in this many days => flag as dormant-but-funded
LARGE_TX_THRESHOLD = 1_000_000      # single transaction above this gets flagged for review
STRUCTURING_THRESHOLD = 500_000     # classic AML reporting-style threshold
STRUCTURING_MARGIN = 0.06           # "just under" = within 6% below the threshold
STRUCTURING_MIN_COUNT = 3           # this many near-threshold deposits on one account = flag
STRUCTURING_WINDOW_DAYS = 14        # ...within this many days of each other

# Minimum balance requirements per Meezan account product (used to flag
# accounts that have dropped below their required minimum).
MIN_BALANCE_BY_ACCOUNT_TYPE = {
    "Rifah Current Account": 0,
    "Meezan Bachat Account": 10000,
    "Meezan Munafa Account": 50000,
    "Meezan Business Plus": 25000,
}


# ---------------------------------------------------------------------------
# SCHEMA
# ---------------------------------------------------------------------------

def get_db_schema():
    """
    Pulls the CREATE TABLE statements directly from SQLite's own metadata
    table (sqlite_master) instead of a hardcoded string. This means if you
    add/rename columns or tables, the LLM's view of the schema is always
    accurate - no manual syncing required.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
        )
        rows = cursor.fetchall()
        return "\n".join(row[0] for row in rows)
    finally:
        conn.close()


def get_allowed_tables():
    """
    Extracts just the table names from the schema (via regex on the
    CREATE TABLE statements). Used to whitelist what the generated SQL
    is allowed to touch.
    """
    schema = get_db_schema()
    return set(re.findall(r"CREATE TABLE\s+(\w+)", schema, flags=re.IGNORECASE))


# ---------------------------------------------------------------------------
# FEW-SHOT EXAMPLES
# A handful of curated (question -> SQL) pairs. This is usually the single
# biggest lever for text-to-SQL accuracy, because it shows the model the
# exact style/joins/date-handling you expect instead of leaving it to guess.
# Update these as you discover real query patterns your users ask for.
# ---------------------------------------------------------------------------

FEW_SHOT_EXAMPLES = """
Example 1:
Q: What is the total balance held at each branch?
A: SELECT b.branch_name, SUM(a.balance) AS total_balance
   FROM accounts a JOIN branches b ON a.branch_id = b.branch_id
   GROUP BY b.branch_name ORDER BY total_balance DESC;

Example 2:
Q: Show me the 5 largest transactions in the last 90 days.
A: SELECT * FROM transactions WHERE tx_date >= date('now', '-90 days') ORDER BY amount DESC LIMIT 5;

Example 3:
Q: What is the average balance by account type?
A: SELECT account_type, AVG(balance) AS avg_balance FROM accounts GROUP BY account_type;

Example 4:
Q: List customers in the Corporate segment along with their account balances.
A: SELECT c.customer_name, a.account_type, a.balance
   FROM customers c JOIN accounts a ON c.customer_id = a.customer_id
   WHERE c.segment = 'Corporate';

Example 5:
Q: How much total deposit volume happened per month this year?
A: SELECT strftime('%Y-%m', tx_date) AS month, SUM(amount) AS total_deposits
   FROM transactions WHERE tx_type = 'Deposit'
   GROUP BY month ORDER BY month;

Example 6:
Q: Which accounts are dormant but still hold a meaningful balance?
A: SELECT a.account_id, c.customer_name, a.account_type, a.balance
   FROM accounts a JOIN customers c ON a.customer_id = c.customer_id
   WHERE a.status = 'Dormant' AND a.balance > 50000;

Example 7:
Q: Show total transaction volume per branch per channel.
A: SELECT b.branch_name, t.channel, SUM(t.amount) AS total_volume
   FROM transactions t
   JOIN accounts a ON t.account_id = a.account_id
   JOIN branches b ON a.branch_id = b.branch_id
   GROUP BY b.branch_name, t.channel ORDER BY total_volume DESC;
"""


# ---------------------------------------------------------------------------
# SQL VALIDATION
# ---------------------------------------------------------------------------

def validate_sql(sql_query, allowed_tables):
    """
    Runs a series of safety checks on LLM-generated SQL BEFORE it ever
    touches the database. Returns (is_valid, reason_if_invalid).

    This is intentionally simple (regex-based) rather than a full SQL
    parser - it's not bulletproof, but it blocks the obvious failure modes:
    non-SELECT statements, forbidden keywords, references to unknown
    tables, and stacked statements.
    """
    upper_sql = sql_query.upper()

    if not upper_sql.startswith("SELECT"):
        return False, "Query must be a SELECT statement."

    # Block stacked statements like "SELECT ...; DROP TABLE ..."
    # (allow a single optional trailing semicolon)
    stripped = sql_query.strip().rstrip(";")
    if ";" in stripped:
        return False, "Multiple SQL statements are not allowed."

    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in upper_sql:
            return False, f"Query contains forbidden keyword: {keyword}"

    # Make sure every table the query references is one we actually know
    # about. We look for identifiers following FROM or JOIN.
    referenced_tables = set(re.findall(r"(?:FROM|JOIN)\s+(\w+)", sql_query, flags=re.IGNORECASE))
    unknown_tables = referenced_tables - allowed_tables
    if unknown_tables:
        return False, f"Query references unknown table(s): {', '.join(unknown_tables)}"

    return True, None


def enforce_row_limit(sql_query, limit=DEFAULT_ROW_LIMIT):
    """
    Appends a LIMIT clause if the query doesn't already have one, so a
    query that (accidentally or not) returns the entire table can't flood
    the UI or eat memory.
    """
    if "LIMIT" not in sql_query.upper():
        return f"{sql_query.rstrip(';')} LIMIT {limit}"
    return sql_query


# ---------------------------------------------------------------------------
# AUDIT LOG
# Every query attempt (successful or not) gets logged to its own table.
# For a banking-contnb ext tool, having a record of "who asked what, what SQL
# ran, and whether it succeeded" is both good practice and a nice thing to
# point to in a portfolio ("I thought about auditability").
# ---------------------------------------------------------------------------

def init_audit_log():
    """Creates the audit log table if it doesn't already exist. Safe to call every run."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS query_audit_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                user_question TEXT,
                generated_sql TEXT,
                status TEXT,
                error_message TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def log_query_attempt(user_question, generated_sql, status, error_message=None):
    """Writes a single row to the audit log."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO query_audit_log (timestamp, user_question, generated_sql, status, error_message) "
            "VALUES (?, ?, ?, ?, ?)",
            (datetime.datetime.now().isoformat(), user_question, generated_sql, status, error_message)
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_query_log(n=10):
    """Returns the n most recent audit log entries as a DataFrame (used by the sidebar in app.py)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(
            "SELECT timestamp, user_question, generated_sql, status FROM query_audit_log "
            "ORDER BY log_id DESC LIMIT ?",
            conn, params=(n,)
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CORE: TEXT -> SQL -> RESULTS, WITH SELF-CORRECTION
# ---------------------------------------------------------------------------

def _call_llm_for_sql(user_question, schema, previous_attempt=None, error_message=None):
    """
    Single call to the LLM to produce a SQL query. If previous_attempt and
    error_message are provided, we tell the model exactly what it tried and
    why it failed, so it can self-correct instead of us just giving up.
    """
    system_prompt = (
        "You are a Meezan Bank Data Analyst. Return ONLY a single, valid SQLite SELECT statement. "
        "Do not provide explanations, do not add markdown, do not use multiple lines.\n"
        f"Schema:\n{schema}\n\n"
        f"Here are some example question -> SQL pairs:\n{FEW_SHOT_EXAMPLES}"
    )

    user_content = f"Question: {user_question}"
    if previous_attempt and error_message:
        # Feed the failure back to the model so it can fix its own mistake
        # instead of us silently returning None to the user.
        user_content += (
            f"\n\nYour previous attempt was: {previous_attempt}\n"
            f"That query failed with this error: {error_message}\n"
            f"Please return a corrected SELECT statement."
        )

    response = client.chat.completions.create(
        model="local-model",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        temperature=0
    )
    sql_query = response.choices[0].message.content.strip()
    # Strip markdown fences in case the model adds them anyway
    sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
    return sql_query


def generate_and_run_sql(user_question):
    """
    Generates SQL from a natural-language question and executes it, with:
      - table/keyword whitelisting (validate_sql)
      - an automatic row LIMIT
      - up to MAX_SQL_RETRIES self-correction attempts if the query fails
      - audit logging of every attempt

    Returns a tuple: (dataframe_or_None, sql_used_or_None, error_message_or_None)
    so the caller (app.py) can show the USER what actually happened instead
    of a generic "query failed".
    """
    schema = get_db_schema()
    allowed_tables = get_allowed_tables()

    previous_sql = None
    last_error = None

    for attempt in range(MAX_SQL_RETRIES + 1):
        sql_query = _call_llm_for_sql(
            user_question, schema,
            previous_attempt=previous_sql, error_message=last_error
        )

        # Step 1: validate before ever touching the database
        is_valid, reason = validate_sql(sql_query, allowed_tables)
        if not is_valid:
            log_query_attempt(user_question, sql_query, "rejected", reason)
            previous_sql, last_error = sql_query, reason
            continue

        # Step 2: enforce a safety row limit
        safe_sql = enforce_row_limit(sql_query)

        # Step 3: actually run it
        df, run_error = run_query(safe_sql, return_error=True)

        if df is not None:
            log_query_attempt(user_question, safe_sql, "success")
            return df, safe_sql, None

        # Query ran but failed (bad column name, syntax error, etc.) -
        # loop around and let the LLM see the real error and try again.
        log_query_attempt(user_question, safe_sql, "failed", run_error)
        previous_sql, last_error = safe_sql, run_error

    # Exhausted all retries
    return None, previous_sql, last_error


def run_query(sql_query, params=None, return_error=False):
    """
    Executes a (already-validated) SQL query and returns a pandas DataFrame.
    Uses parameterized queries via `params` so values (like a selected
    customer name) are never string-interpolated directly into SQL -
    this is what prevents SQL injection on the drill-down query in app.py.

    If return_error=True, returns (df_or_None, error_message_or_None)
    instead of just df, so callers can surface *why* something failed.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(sql_query, conn, params=params)
        return (df, None) if return_error else df
    except Exception as e:
        return (None, str(e)) if return_error else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# RISK-SIGNAL LAYER
# Instead of asking the LLM to "assess risk" purely from a raw table dump
# (which means it's essentially guessing), we compute a few deterministic,
# explainable signals in plain pandas first. These get handed to the LLM
# as grounding facts, and it explains/prioritizes them rather than
# inventing them. This is also what turns the tool from "a chatbot on top
# of SQL" into something closer to an actual recommendation engine: the
# flags are reproducible and you can defend them if someone asks why the
# system raised a concern.
# ---------------------------------------------------------------------------

def compute_risk_signals(df):
    """
    Looks at whichever relevant columns are present in the CURRENT result
    set and returns a list of (message, severity) tuples, grounded in real
    banking-analyst concerns rather than generic statistics:

      1. Minimum balance breaches (product-specific, not a flat threshold)
      2. Dormant-but-funded accounts (no activity in DORMANCY_DAYS)
      3. Large single transactions above LARGE_TX_THRESHOLD
      4. Structuring patterns - several deposits clustered just under
         STRUCTURING_THRESHOLD within a short window on the same account,
         a well-known real-world AML red flag
      5. Month-over-month volume swings

    severity is one of: "high", "medium", "info", "neutral" - the caller
    (app.py) uses this to color-code each signal rather than guessing from
    the text. Each rule only runs if the columns it needs are actually
    present in the query result, since the user's question determines what
    columns come back (e.g. a "top branches by balance" query won't have
    tx_date).
    """
    signals = []

    # --- 1. Minimum balance breaches (per-product, not a flat number) ---
    if "balance" in df.columns and "account_type" in df.columns:
        breaches = df[df.apply(
            lambda row: row["balance"] < MIN_BALANCE_BY_ACCOUNT_TYPE.get(row["account_type"], 0),
            axis=1
        )]
        if not breaches.empty:
            signals.append((
                f"{len(breaches)} account(s) are below the minimum balance "
                f"required for their product type.",
                "medium"
            ))

    # --- 2. Dormant-but-funded accounts ---
    if "status" in df.columns and "balance" in df.columns:
        dormant_funded = df[(df["status"] == "Dormant") & (df["balance"] > 0)]
        if not dormant_funded.empty:
            total_dormant_balance = dormant_funded["balance"].sum()
            signals.append((
                f"{len(dormant_funded)} dormant account(s) are still holding a combined "
                f"PKR {total_dormant_balance:,.0f} - candidates for reactivation outreach.",
                "medium"
            ))

    # --- 3. Large single transactions ---
    if "amount" in df.columns:
        large_tx = df[df["amount"] > LARGE_TX_THRESHOLD]
        if not large_tx.empty:
            signals.append((
                f"{len(large_tx)} transaction(s) exceed the PKR {LARGE_TX_THRESHOLD:,} "
                f"single-transaction review threshold.",
                "high"
            ))

    # --- 4. Structuring pattern (near-threshold deposits, clustered in time) ---
    # This only works if we have per-account, per-date detail (i.e. the
    # query returned raw transaction rows, not an aggregate).
    if {"account_id", "tx_date", "amount"}.issubset(df.columns):
        try:
            temp = df.copy()
            temp["tx_date"] = pd.to_datetime(temp["tx_date"], errors="coerce")
            near_threshold = temp[
                (temp["amount"] >= STRUCTURING_THRESHOLD * (1 - STRUCTURING_MARGIN)) &
                (temp["amount"] < STRUCTURING_THRESHOLD)
            ]
            flagged_accounts = 0
            for acc_id, group in near_threshold.groupby("account_id"):
                dates = group["tx_date"].dropna().sort_values()
                if len(dates) >= STRUCTURING_MIN_COUNT:
                    span_days = (dates.iloc[-1] - dates.iloc[0]).days
                    if span_days <= STRUCTURING_WINDOW_DAYS:
                        flagged_accounts += 1
            if flagged_accounts:
                signals.append((
                    f"{flagged_accounts} account(s) show a possible structuring pattern - "
                    f"multiple deposits just under the PKR {STRUCTURING_THRESHOLD:,} threshold "
                    f"within a {STRUCTURING_WINDOW_DAYS}-day window.",
                    "high"
                ))
        except Exception:
            pass

    # --- 5. Month-over-month volume swing ---
    if "tx_date" in df.columns and "amount" in df.columns:
        try:
            temp = df.copy()
            temp["tx_date"] = pd.to_datetime(temp["tx_date"], errors="coerce")
            temp = temp.dropna(subset=["tx_date"])
            if not temp.empty:
                monthly = temp.set_index("tx_date").resample("ME")["amount"].sum()
                if len(monthly) >= 2 and monthly.iloc[-2] != 0:
                    pct_change = (monthly.iloc[-1] - monthly.iloc[-2]) / abs(monthly.iloc[-2]) * 100
                    if abs(pct_change) >= 20:
                        direction = "increase" if pct_change > 0 else "decline"
                        signals.append((
                            f"Month-over-month transaction volume shows a {abs(pct_change):.1f}% {direction}.",
                            "info"
                        ))
        except Exception:
            # Risk signals are a "nice to have" layer - if date parsing
            # fails for any reason, we just skip this signal rather than
            # breaking the whole analysis.
            pass

    if not signals:
        signals.append(("No notable risk signals detected in this result set.", "neutral"))

    return signals


def analyze_results(user_question, df):
    """
    Translates DataFrame results into professional insights, grounded by
    the deterministic risk signals computed above (rather than asking the
    LLM to invent risk assessments from scratch).
    """
    risk_signals = compute_risk_signals(df)
    signals_text = "\n".join(f"- {text}" for text, severity in risk_signals)

    analysis_prompt = f"""
    User Question: {user_question}
    Data:
    {df.to_string()}

    Computed risk/opportunity signals (already calculated - explain and
    prioritize these, do not invent new numeric claims beyond what's listed):
    {signals_text}

    Role: Senior Financial Analyst at Meezan Bank, a full-fledged Islamic bank.

    Important framing notes:
    - This is an Islamic bank: refer to "profit" or "profit rate", never
      "interest" - Meezan operates on Shariah-compliant, profit-and-loss
      sharing principles, not conventional interest-based banking.
    - Product names you may see: "Rifah Current Account" (non-profit-bearing
      current account), "Meezan Bachat Account" and "Meezan Munafa Account"
      (profit-bearing savings products), "Meezan Business Plus" (SME/business
      current account).

    Task: Write a concise, formal analyst note with:
    1. A 3-bullet summary of what the data shows.
    2. A risk/opportunity assessment grounded ONLY in the computed signals
       above - reference the specific numbers given, don't invent new ones.
    3. A direct, concrete recommendation a branch manager could act on this
       week (e.g. "refer account X for AML review", "assign a relationship
       officer to re-engage dormant customers", "offer a Meezan Munafa
       Account upgrade to customers holding idle current-account balances").
    If no signals were flagged, say so plainly rather than manufacturing a concern.
    """
    response = client.chat.completions.create(
        model="local-model",
        messages=[{"role": "user", "content": analysis_prompt}]
    )
    return response.choices[0].message.content


# Make sure the audit log table exists as soon as this module is imported.
init_audit_log()
