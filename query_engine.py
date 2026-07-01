import sqlite3
from openai import OpenAI

# Initialize the client pointing to your local LM Studio server
# The API key is not actually checked by LM Studio, so we pass a placeholder.
client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

def get_db_schema():
    """
    Extracts table and column names from the SQLite database
    to provide the LLM with context (the 'map').
    """
    conn = sqlite3.connect('bank_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    schema = ""
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table[0]})")
        columns = cursor.fetchall()
        schema += f"Table: {table[0]}, Columns: {[col[1] for col in columns]}\n"
    conn.close()
    return schema

def generate_and_run_sql(user_question):
    schema = get_db_schema()
    
    # SYSTEM PROMPT: Defines the AI's boundaries.
    # We strictly limit the AI to SELECT queries for security.
    system_prompt = (
        "You are a banking database assistant. "
        "Return ONLY valid SQLite SQL code. "
        "Strictly ONLY SELECT statements are allowed. "
        "If the user asks for anything else (DELETE, DROP, UPDATE), refuse it."
    )
    
    # STAGE 2: Reasoning Phase (Send to LM Studio)
    try:
        response = client.chat.completions.create(
            model="local-model", # The specific name doesn't matter for LM Studio
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Schema:\n{schema}\n\nQuestion: {user_question}"}
            ],
            temperature=0  # Set to 0 for maximum logic/consistency
        )
        sql_query = response.choices[0].message.content.strip()
    except Exception as e:
        return f"LLM Error: {e}"
    
    # STAGE 3: Guardrail
    if not sql_query.upper().startswith("SELECT"):
        return "Error: Security violation. Only SELECT queries are permitted."
    
    # STAGE 4: Execution Phase
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
    """
    Takes raw SQL data and turns it into professional banking insights.
    """
    # We pass the question and the data back to Llama 3.1 8B for interpretation
    analysis_prompt = (
        f"User Question: '{user_question}'\n"
        f"Database Result: {sql_results}\n"
        "Act as a Meezan Bank Branch Manager Assistant. "
        "Summarize this data professionally. "
        "If the data is numerical, suggest if this is a positive/negative trend. "
        "Keep it concise, professional, and actionable."
    )
    
    response = client.chat.completions.create(
        model="local-model",
        messages=[{"role": "user", "content": analysis_prompt}]
    )
    return response.choices[0].message.content

# --- Test ---
if __name__ == "__main__":
    question = "What is the balance for Dawar Malik?"
    print(f"Question: {question}")
    print(f"Result: {generate_and_run_sql(question)}")