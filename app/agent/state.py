"""
LangGraph state definition.

Plain TypedDict (not a Pydantic model) because LangGraph merges partial
state updates returned by each node into this dict; TypedDict +
Annotated reducers is the standard, lightest-weight way to express that
in LangGraph. guard_results uses operator.add as its reducer so each
node's new GuardResult(s) get appended to the running list rather than
overwriting it -- every other field is last-write-wins (LangGraph's
default), which is correct for fields like generated_sql that should be
replaced wholesale on repair, not merged.

parsed_sql intentionally holds a live app.guards.sql_analysis.ParsedSQL
object (not a JSON-safe dict) -- this graph runs entirely in-process for
a single request with no checkpointing/persistence configured, so it
never needs to be serialized. Don't put this field in any API response
model; app/api/schemas.py works from guard_results and sql_metadata
instead.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional, TypedDict


class AgentState(TypedDict, total=False):
    request_id: str
    user_query: str

    intent_result: Optional[dict]  # {"allowed": bool, "category": str, "risk": str, "reason": str}

    retrieved_schema: Optional[list[str]]  # table names retrieved, for audit/UI
    schema_context: Optional[str]  # rendered text handed to the SQL generation prompt

    generated_sql: Optional[str]
    sql_metadata: Optional[dict]  # {"tables_used": [...], "joins": int, "query_type": str}
    parsed_sql: Optional[Any]  # app.guards.sql_analysis.ParsedSQL -- in-process only, see docstring

    guard_results: Annotated[list[dict], operator.add]
    repair_attempted: bool
    repair_reason: Optional[str]

    execution_result: Optional[dict]  # {"rows": [...], "columns": [...], "row_count": int, "truncated": bool}
    final_answer: Optional[str]

    status: Literal["PENDING", "SUCCESS", "BLOCKED", "ERROR"]
    blocked_guard: Optional[str]  # which guard produced the terminal BLOCKED verdict, for the UI
    error: Optional[str]
    start_time: float  # time.monotonic() at request start -- internal, never serialized to the API
    latency_ms: Optional[int]


def new_agent_state(request_id: str, user_query: str, start_time: float) -> AgentState:
    """Construct the initial state LangGraph starts a run with."""
    return AgentState(
        request_id=request_id,
        user_query=user_query,
        intent_result=None,
        retrieved_schema=None,
        schema_context=None,
        generated_sql=None,
        sql_metadata=None,
        parsed_sql=None,
        guard_results=[],
        repair_attempted=False,
        repair_reason=None,
        execution_result=None,
        final_answer=None,
        status="PENDING",
        blocked_guard=None,
        error=None,
        start_time=start_time,
        latency_ms=None,
    )
