"""
Top-level entry point for running the agent graph for a single request.

app.api.routes (Stage 7) and scripts/run_evaluation.py (Stage 8) both
call run_agent() -- neither talks to app.agent.graph directly, so
request ID generation and request-level timing live in exactly one
place.
"""

from __future__ import annotations

import time
import uuid

from app.agent.graph import compiled_graph
from app.agent.state import AgentState, new_agent_state


def run_agent(user_query: str) -> AgentState:
    request_id = str(uuid.uuid4())
    start_time = time.monotonic()
    initial_state = new_agent_state(request_id, user_query, start_time)
    final_state = compiled_graph.invoke(initial_state)
    return final_state
