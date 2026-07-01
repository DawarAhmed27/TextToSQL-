import streamlit as st
from query_engine import generate_and_run_sql, analyze_results

st.set_page_config(page_title="Meezan Branch Insights", layout="wide")
st.title("🏦 Meezan Bank: AI Branch Analyst")

question = st.text_input("Ask a question about branch performance:")

if st.button("Analyze"):
    if question:
        with st.spinner("Analyzing data..."):
            # 1. Run the SQL
            raw_data = generate_and_run_sql(question)
            
            # 2. Display Raw Data
            st.subheader("Raw Data:")
            st.write(raw_data)
            
            # 3. Display AI Insight
            insight = analyze_results(question, raw_data)
            st.subheader("Manager Insight:")
            st.success(insight) 