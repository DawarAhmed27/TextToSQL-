import sqlite3
from openai import OpenAI

client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

def get_db_schema():
    # We pass a clean, literal schema string to the LLM
    return """
    Table: accounts (account_id INTEGER, customer_name TEXT, balance REAL)
    Table: transactions (tx_id INTEGER, account_id INTEGER, amount REAL, tx_date TEXT)
    """

def generate_and_run_sql(user_question):
    schema = get_db_schema()
    
    # SYSTEM PROMPT: Now strictly formatted to prevent hallucinations
    system_prompt = (
        "You are a Meezan Bank Data Analyst. Convert natural language to a SINGLE valid SQLite SELECT statement. "
        "Use only these tables and columns:\n" + schema + "\n"
        "Return ONLY the SQL string. Do not explain, do not add markdown (like ```sql), do not use multiple lines."
    )
    
    try:
        response = client.chat.completions.create(
            model="local-model",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Question: {user_question}"}
            ],
            temperature=0
        )
        sql_query = response.choices[0].message.content.strip()
        # Remove markdown artifacts if the model ignores our instruction
        sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
        
    except Exception as e:
        return f"LLM Error: {e}"
    
    # SAFETY: Ensure only SELECT
    if not sql_query.upper().startswith("SELECT"):
        return f"Security Error: Model attempted to run non-SELECT query: {sql_query}"
    
    # EXECUTION: Single statement check
    try:
        conn = sqlite3.connect('bank_data.db')
        cursor = conn.cursor()
        cursor.execute(sql_query)
        results = cursor.fetchall()
        conn.close()
        return results
    except Exception as e:
        return f"Database Error: {e}"

def analyze_results(user_question, sql_results):
    # This remains the same as before
    prompt = (
        f"User asked: {user_question}\n"
        f"SQL Result: {sql_results}\n"
        "Summarize this for a Branch Manager. Be professional, indicate trends if possible, and suggest one action."
    )
    response = client.chat.completions.create(
        model="local-model",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content