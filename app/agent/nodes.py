"""
LangGraph node implementations.

Each node function takes AgentState and returns a partial dict of
updates -- the shape LangGraph expects. Nodes that can fail terminally
(retrieve_schema, generate_sql, execute) set status="ERROR" themselves
directly in their return value; guard nodes never set terminal status
themselves -- that's decided by the routing functions in
app.agent.graph, which is what keeps "is this failure repairable"
logic in exactly one place (app.guards.models.GuardResult.repairable)
rather than re-derived per node.

function_guard's check is folded into validate_ast_node rather than
given its own graph node/edge, since the spec's own LangGraph node list
(section 30) only names validate_ast/check_policy/check_pii/
check_complexity -- dangerous-function checking is AST-derived
(depends on the same parsed tree, no policy dependency) and belongs
alongside AST validation structurally, without inventing a 5th graph
node the spec didn't ask for.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from pydantic import ValidationError

from app.agent.state import AgentState
from app.core.logging import write_audit_record
from app.executor.executor import execute_safe_sql
from app.guards.ast_guard import validate_ast
from app.guards.complexity_guard import check_complexity
from app.guards.function_guard import check_functions
from app.guards.pii_guard import check_pii
from app.guards.policy_guard import check_policy
from app.llm.base import LLMOutputParseError, LLMProviderError, get_llm_provider
from app.llm.generator import SQLGenerationError, SQLGenerationResult, generate_sql
from app.llm.prompts import (
    build_intent_classification_prompt,
    build_repair_prompt,
    build_result_formatting_prompt,
)
from app.schema.metadata import render_table_document
from app.schema.retriever import retrieve_relevant_schema


# ---------------------------------------------------------------------
# 1. classify_intent
# ---------------------------------------------------------------------
def classify_intent(state: AgentState) -> dict:
    system_prompt, user_prompt = build_intent_classification_prompt(state["user_query"])
    provider = get_llm_provider()

    try:
        intent_result = provider.complete_json(system_prompt, user_prompt)
    except (LLMProviderError, LLMOutputParseError) as e:
        # Intent classification is an early filter, NOT the security
        # boundary (spec section 5) -- if the classifier itself is
        # unavailable, fail OPEN here and let the real, deterministic
        # guardrail pipeline downstream be the actual gate. The failure
        # is still recorded for audit visibility.
        return {
            "intent_result": {
                "allowed": True,
                "category": "unknown",
                "risk": "medium",
                "reason": f"Intent classification unavailable, proceeding to guarded pipeline: {e}",
            }
        }

    if not intent_result.get("allowed", True):
        return {
            "intent_result": intent_result,
            "status": "BLOCKED",
            "blocked_guard": "intent",
            "error": intent_result.get("reason", "Blocked by intent classification."),
        }

    return {"intent_result": intent_result}


# ---------------------------------------------------------------------
# 2. retrieve_schema
# ---------------------------------------------------------------------
def retrieve_schema_node(state: AgentState) -> dict:
    retrieved = retrieve_relevant_schema(state["user_query"])

    if not retrieved:
        return {
            "retrieved_schema": [],
            "schema_context": "",
            "status": "ERROR",
            "error": "No schema index found or nothing matched. Run `python scripts/index_schema.py` first.",
        }

    table_names = [rt.table.name for rt in retrieved]
    schema_context = "\n\n".join(render_table_document(rt.table) for rt in retrieved)
    return {"retrieved_schema": table_names, "schema_context": schema_context}


# ---------------------------------------------------------------------
# 3. generate_sql
# ---------------------------------------------------------------------
def generate_sql_node(state: AgentState) -> dict:
    try:
        result = generate_sql(state["user_query"], state["schema_context"])
    except (SQLGenerationError, LLMProviderError) as e:
        return {"status": "ERROR", "error": f"SQL generation failed: {e}"}

    return {
        "generated_sql": result.sql,
        "sql_metadata": {
            "tables_used": result.tables_used,
            "joins": result.joins,
            "query_type": result.query_type,
        },
    }


# ---------------------------------------------------------------------
# 4. validate_ast (+ function guard, folded in -- see module docstring)
# ---------------------------------------------------------------------
def validate_ast_node(state: AgentState) -> dict:
    ast_result, parsed = validate_ast(state["generated_sql"])
    new_results = [ast_result.model_dump(mode="json")]

    if not ast_result.is_pass():
        return {"guard_results": new_results, "parsed_sql": None}

    func_result = check_functions(parsed)
    new_results.append(func_result.model_dump(mode="json"))

    if not func_result.is_pass():
        return {"guard_results": new_results, "parsed_sql": None}

    return {"guard_results": new_results, "parsed_sql": parsed}


# ---------------------------------------------------------------------
# 5. check_policy
# ---------------------------------------------------------------------
def check_policy_node(state: AgentState) -> dict:
    result = check_policy(state["parsed_sql"])
    return {"guard_results": [result.model_dump(mode="json")]}


# ---------------------------------------------------------------------
# 6. check_pii
# ---------------------------------------------------------------------
def check_pii_node(state: AgentState) -> dict:
    result = check_pii(state["parsed_sql"])
    return {"guard_results": [result.model_dump(mode="json")]}


# ---------------------------------------------------------------------
# 7. check_complexity
# ---------------------------------------------------------------------
def check_complexity_node(state: AgentState) -> dict:
    result = check_complexity(state["parsed_sql"])
    return {"guard_results": [result.model_dump(mode="json")]}


# ---------------------------------------------------------------------
# repair (at most once -- enforced both here and by the router)
# ---------------------------------------------------------------------
def repair_node(state: AgentState) -> dict:
    if state.get("repair_attempted"):
        # Defensive only -- app.agent.graph's routing already prevents
        # reaching this node a second time (repairable check requires
        # `not state.get("repair_attempted")`).
        return {
            "status": "BLOCKED",
            "blocked_guard": "repair",
            "error": "Repair already attempted once; not retrying again.",
        }

    last_failure = state["guard_results"][-1] if state["guard_results"] else {}
    failure_reason = last_failure.get("reason", "validation failed")

    system_prompt, user_prompt = build_repair_prompt(
        state["user_query"], state["schema_context"], state["generated_sql"], failure_reason
    )
    provider = get_llm_provider()

    try:
        raw = provider.complete_json(system_prompt, user_prompt)
        result = SQLGenerationResult.model_validate(raw)
    except (LLMProviderError, LLMOutputParseError, ValidationError) as e:
        return {
            "status": "ERROR",
            "error": f"Repair attempt failed: {e}",
            "repair_attempted": True,
            "repair_reason": failure_reason,
        }

    return {
        "generated_sql": result.sql,
        "sql_metadata": {
            "tables_used": result.tables_used,
            "joins": result.joins,
            "query_type": result.query_type,
        },
        "repair_attempted": True,
        "repair_reason": failure_reason,
    }


# ---------------------------------------------------------------------
# terminal-failure marker (guard FAIL, not repairable / already repaired once)
# ---------------------------------------------------------------------
def mark_blocked_node(state: AgentState) -> dict:
    last = state["guard_results"][-1] if state["guard_results"] else None
    guard_name = last["guard_name"] if last else "unknown"
    reason = (last or {}).get("reason") or "Blocked by guardrail pipeline."
    return {"status": "BLOCKED", "blocked_guard": guard_name, "error": reason}


# ---------------------------------------------------------------------
# 8. execute
# ---------------------------------------------------------------------
def execute_node(state: AgentState) -> dict:
    result = execute_safe_sql(state["generated_sql"])
    execution_result = {
        "success": result.success,
        "rows": result.rows,
        "columns": result.columns,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }

    if not result.success:
        return {"execution_result": execution_result, "status": "ERROR", "error": result.error}

    return {"execution_result": execution_result}


# ---------------------------------------------------------------------
# 9. format_result
# ---------------------------------------------------------------------
def format_result_node(state: AgentState) -> dict:
    execution_result = state["execution_result"]

    if execution_result["row_count"] == 0:
        return {"final_answer": "No results were found for this question.", "status": "SUCCESS"}

    system_prompt, user_prompt = build_result_formatting_prompt(
        state["user_query"], execution_result["columns"], execution_result["rows"]
    )
    provider = get_llm_provider()

    try:
        answer = provider.complete(system_prompt, user_prompt)
    except LLMProviderError:
        # The user already has valid, correct rows -- a formatting-call
        # failure shouldn't turn a successful query into an error.
        # Fall back to a plain templated summary instead.
        answer = f"Found {execution_result['row_count']} result(s)."

    return {"final_answer": answer.strip(), "status": "SUCCESS"}


# ---------------------------------------------------------------------
# 10. audit
# ---------------------------------------------------------------------
def audit_node(state: AgentState) -> dict:
    latency_ms = int((time.monotonic() - state["start_time"]) * 1000)
    execution_result = state.get("execution_result") or {}

    record = {
        "request_id": state.get("request_id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_query": state.get("user_query"),
        "intent_result": state.get("intent_result"),
        "retrieved_schema": state.get("retrieved_schema"),
        # sql_metadata only -- NEVER the raw generated_sql text, which
        # can contain literal values echoed from the question.
        "sql_metadata": state.get("sql_metadata"),
        "guard_results": state.get("guard_results"),
        "repair_attempted": state.get("repair_attempted", False),
        "execution_status": "success" if execution_result.get("success") else None,
        # Row COUNT only -- never the row data itself.
        "rows_returned": execution_result.get("row_count"),
        "latency_ms": latency_ms,
        "final_status": state.get("status"),
    }

    write_audit_record(record)
    return {"latency_ms": latency_ms}
