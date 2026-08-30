"""
LangGraph orchestration (spec section 30).

    START
      v
    classify_intent -----------------------------[BLOCKED]--> audit --> END
      v [continue]
    retrieve_schema --------------------------------[ERROR]--> audit --> END
      v [continue]
    generate_sql ------------------------------------[ERROR]--> audit --> END
      v [continue]
    validate_ast (+ function guard)
      |--[PASS]--> check_policy
      |--[FAIL, repairable, no repair yet]--> repair --> validate_ast (re-run ALL guards)
      |--[FAIL, not repairable / already repaired]--> mark_blocked --> audit --> END
    check_policy / check_pii / check_complexity follow the exact same
      three-way branch as validate_ast, chained in that fixed order.
      v [continue after check_complexity]
    execute -----------------------------------------[ERROR]--> audit --> END
      v [continue]
    format_result --> audit --> END

This is a strict sequential dependency chain end to end -- exactly what
spec section 4 requires ("do NOT implement the architecture as parallel
independent branches"). Every guard shares one router
(`_route_after_guard`) because they all obey the identical rule: PASS
continues to the next guard, a repairable FAIL gets exactly one repair
attempt (then MUST re-run every guard from scratch, never resuming
partway through), and anything else blocks. Encoding that rule once,
here, is what guarantees a security-relevant guard failure can never be
silently repaired into execution -- there is no code path that skips
straight from a guard FAIL to `execute`.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    audit_node,
    check_complexity_node,
    check_pii_node,
    check_policy_node,
    classify_intent,
    execute_node,
    format_result_node,
    generate_sql_node,
    mark_blocked_node,
    repair_node,
    retrieve_schema_node,
    validate_ast_node,
)
from app.agent.state import AgentState


def _route_terminal_or_continue(state: AgentState) -> Literal["continue", "terminal"]:
    """Used after classify_intent / retrieve_schema / generate_sql / execute."""
    return "terminal" if state.get("status") in ("BLOCKED", "ERROR") else "continue"


def _route_after_guard(state: AgentState) -> Literal["continue", "repair", "blocked"]:
    """Used after validate_ast / check_policy / check_pii / check_complexity."""
    results = state.get("guard_results") or []
    if not results:
        return "continue"

    last = results[-1]
    if last["status"] == "PASS":
        return "continue"

    if last.get("repairable") and not state.get("repair_attempted"):
        return "repair"

    return "blocked"


def _route_after_repair(state: AgentState) -> Literal["revalidate", "terminal"]:
    return "terminal" if state.get("status") == "ERROR" else "revalidate"


def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("classify_intent", classify_intent)
    builder.add_node("retrieve_schema", retrieve_schema_node)
    builder.add_node("generate_sql", generate_sql_node)
    builder.add_node("validate_ast", validate_ast_node)
    builder.add_node("check_policy", check_policy_node)
    builder.add_node("check_pii", check_pii_node)
    builder.add_node("check_complexity", check_complexity_node)
    builder.add_node("repair", repair_node)
    builder.add_node("mark_blocked", mark_blocked_node)
    builder.add_node("execute", execute_node)
    builder.add_node("format_result", format_result_node)
    builder.add_node("audit", audit_node)

    builder.set_entry_point("classify_intent")

    builder.add_conditional_edges(
        "classify_intent", _route_terminal_or_continue, {"continue": "retrieve_schema", "terminal": "audit"}
    )
    builder.add_conditional_edges(
        "retrieve_schema", _route_terminal_or_continue, {"continue": "generate_sql", "terminal": "audit"}
    )
    builder.add_conditional_edges(
        "generate_sql", _route_terminal_or_continue, {"continue": "validate_ast", "terminal": "audit"}
    )

    builder.add_conditional_edges(
        "validate_ast",
        _route_after_guard,
        {"continue": "check_policy", "repair": "repair", "blocked": "mark_blocked"},
    )
    builder.add_conditional_edges(
        "check_policy",
        _route_after_guard,
        {"continue": "check_pii", "repair": "repair", "blocked": "mark_blocked"},
    )
    builder.add_conditional_edges(
        "check_pii",
        _route_after_guard,
        {"continue": "check_complexity", "repair": "repair", "blocked": "mark_blocked"},
    )
    builder.add_conditional_edges(
        "check_complexity",
        _route_after_guard,
        {"continue": "execute", "repair": "repair", "blocked": "mark_blocked"},
    )

    # Repair always re-enters at validate_ast -- never resumes partway
    # through the guard chain. This is what "never execute repaired SQL
    # without re-running all guards" (spec section 13) means in practice.
    builder.add_conditional_edges(
        "repair", _route_after_repair, {"revalidate": "validate_ast", "terminal": "audit"}
    )

    builder.add_conditional_edges(
        "execute", _route_terminal_or_continue, {"continue": "format_result", "terminal": "audit"}
    )

    builder.add_edge("format_result", "audit")
    builder.add_edge("mark_blocked", "audit")
    builder.add_edge("audit", END)

    return builder.compile()


# Compiled once at import time -- LangGraph graphs are stateless
# blueprints; a fresh AgentState is created per request (see
# app.agent.runner), so sharing one compiled graph across requests is
# safe and avoids rebuilding it on every call.
compiled_graph = build_graph()
