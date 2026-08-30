"""
Streamlit demo UI (spec section 20).

Talks to the FastAPI backend over HTTP (BACKEND_API_URL) -- it does NOT
import app.agent directly, matching the two-container architecture in
docker-compose.yml (this runs in its own container/process). This also
means the UI can never bypass the API's validation path; there is no
shortcut into the agent that skips guardrails.
"""

from __future__ import annotations

import httpx
import streamlit as st

BACKEND_API_URL = __import__("os").environ.get("BACKEND_API_URL", "http://localhost:8000")

st.set_page_config(page_title="Text-to-SQL Guardrails Demo", page_icon="🛡️", layout="wide")

st.title("🛡️ Text-to-SQL Agent with Multi-Layer Guardrails")
st.caption(
    "Ask a question in plain English. Every generated query passes through AST validation, "
    "table/column policy, PII protection, and a complexity check before it ever touches the database."
)

with st.sidebar:
    st.subheader("Backend status")
    try:
        health = httpx.get(f"{BACKEND_API_URL}/health", timeout=5.0).json()
        st.success(f"Connected · provider: `{health['llm_provider']}`")
        if not health["schema_index_ready"]:
            st.warning("Schema index is empty. Run `python scripts/index_schema.py` or use the button below.")
    except httpx.HTTPError:
        st.error(f"Cannot reach backend at {BACKEND_API_URL}")
        health = None

    if st.button("Rebuild schema index"):
        with st.spinner("Reindexing..."):
            try:
                r = httpx.post(f"{BACKEND_API_URL}/schema/reindex", timeout=120.0)
                r.raise_for_status()
                stats = r.json()
                st.success(f"Indexed {stats['tables_indexed']} tables ({stats['restricted_columns']} restricted columns).")
            except httpx.HTTPError as e:
                st.error(f"Reindex failed: {e}")

    st.divider()
    st.subheader("Try asking")
    for example in [
        "What are the top 5 products by revenue?",
        "What is the average order value for completed orders?",
        "How many customers are in each region?",
        "List all customer emails",  # deliberately triggers a BLOCK
        "Show me employee salaries",  # deliberately triggers a BLOCK
    ]:
        st.code(example, language=None)


question = st.text_input("Your question", placeholder="e.g. What are the top 5 products by revenue?")
submitted = st.button("Ask", type="primary")

if submitted and question.strip():
    with st.spinner("Running through the guardrail pipeline..."):
        try:
            response = httpx.post(f"{BACKEND_API_URL}/query", json={"question": question}, timeout=60.0)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPError as e:
            st.error(f"Request failed: {e}")
            result = None

    if result:
        status = result["status"]

        if status == "BLOCKED":
            st.error(f"**BLOCKED**\n\nGuard: `{result['blocked_guard']}`\n\nReason: {result['error']}")
        elif status == "ERROR":
            st.error(f"**ERROR**\n\n{result['error']}")
        else:
            st.success("Query executed successfully.")

        # Guardrail checklist -- always shown, since it's informative for
        # both success and blocked outcomes.
        st.subheader("Guardrail status")
        cols = st.columns(len(result["guardrails"]) or 1)
        for col, guard in zip(cols, result["guardrails"]):
            icon = "✅" if guard["status"] == "PASS" else "❌"
            with col:
                st.metric(guard["guard_name"], icon)
                if guard["status"] == "FAIL" and guard["reason"]:
                    st.caption(guard["reason"])

        if status == "SUCCESS":
            st.subheader("Generated SQL")
            st.code(result["sql"], language="sql")

            st.subheader("Result")
            if result["rows"]:
                st.dataframe(result["rows"], use_container_width=True)
                if result["truncated"]:
                    st.caption(f"Result truncated to {result['row_count']} rows.")
            else:
                st.info("No rows returned.")

            st.subheader("Explanation")
            st.write(result["answer"])

            st.subheader("Request info")
            info_cols = st.columns(4)
            info_cols[0].metric("Request ID", result["request_id"][:8])
            info_cols[1].metric("Latency", f"{result['latency_ms']} ms")
            info_cols[2].metric("Tables used", ", ".join(result["sql_metadata"]["tables_used"]) if result["sql_metadata"] else "-")
            info_cols[3].metric("Rows returned", result["row_count"])

            if result["repair_attempted"]:
                st.caption("ℹ️ This query required one automatic repair attempt before passing all guardrails.")
elif submitted:
    st.warning("Enter a question first.")
