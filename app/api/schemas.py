"""
Pydantic request/response models for the FastAPI layer (spec section 19).

Deliberately built from AgentState's already-JSON-safe fields (see
app.executor.executor._to_json_safe and app.agent.state's docstring)
rather than re-deriving formatting logic here.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, examples=["What are the top 5 products by revenue?"])


class GuardResultResponse(BaseModel):
    guard_name: str
    status: Literal["PASS", "FAIL"]
    reason: Optional[str] = None
    repairable: bool = False


class QueryResponse(BaseModel):
    request_id: str
    status: Literal["SUCCESS", "BLOCKED", "ERROR"]
    answer: Optional[str] = None
    sql: Optional[str] = None
    sql_metadata: Optional[dict] = None
    columns: Optional[list[str]] = None
    rows: Optional[list[dict]] = None
    row_count: Optional[int] = None
    truncated: Optional[bool] = None
    guardrails: list[GuardResultResponse] = Field(default_factory=list)
    blocked_guard: Optional[str] = None
    error: Optional[str] = None
    repair_attempted: bool = False
    latency_ms: Optional[int] = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    llm_provider: str
    schema_index_ready: bool


class ReindexResponse(BaseModel):
    tables_indexed: int
    restricted_columns: int


class AuditRecordResponse(BaseModel):
    request_id: str
    timestamp: str
    user_query: str
    intent_result: Optional[dict] = None
    retrieved_schema: Optional[list[str]] = None
    sql_metadata: Optional[dict] = None
    guard_results: list[dict] = Field(default_factory=list)
    repair_attempted: bool = False
    execution_status: Optional[str] = None
    rows_returned: Optional[int] = None
    latency_ms: Optional[int] = None
    final_status: Optional[str] = None
