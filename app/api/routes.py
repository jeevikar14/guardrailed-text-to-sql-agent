"""
FastAPI application (spec section 19).

    GET  /health
    POST /query
    POST /schema/reindex
    GET  /audit/{request_id}

This module defines the `app` object uvicorn serves (see Dockerfile:
`uvicorn app.api.routes:app`). All business logic lives in
app.agent.runner / app.schema.indexer / app.core.logging -- this file
only translates between HTTP and those calls.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.agent.runner import run_agent
from app.api.schemas import (
    AuditRecordResponse,
    GuardResultResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    ReindexResponse,
)
from app.core.config import settings
from app.core.logging import find_audit_record
from app.schema.indexer import get_client, get_collection, rebuild_schema_index

app = FastAPI(
    title="Text-to-SQL Agent with Multi-Layer Guardrails",
    description="Natural-language querying over PostgreSQL with deterministic SQL guardrails.",
    version="0.1.0",
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        collection = get_collection(get_client())
        schema_index_ready = collection.count() > 0
    except Exception:
        schema_index_ready = False

    return HealthResponse(status="ok", llm_provider=settings.llm_provider, schema_index_ready=schema_index_ready)


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    state = run_agent(request.question)

    execution_result = state.get("execution_result") or {}
    guardrails = [
        GuardResultResponse(
            guard_name=g["guard_name"], status=g["status"], reason=g.get("reason"), repairable=g.get("repairable", False)
        )
        for g in state.get("guard_results", [])
    ]

    return QueryResponse(
        request_id=state["request_id"],
        status=state["status"],
        answer=state.get("final_answer"),
        sql=state.get("generated_sql") if state["status"] == "SUCCESS" else None,
        sql_metadata=state.get("sql_metadata"),
        columns=execution_result.get("columns"),
        rows=execution_result.get("rows"),
        row_count=execution_result.get("row_count"),
        truncated=execution_result.get("truncated"),
        guardrails=guardrails,
        blocked_guard=state.get("blocked_guard"),
        error=state.get("error"),
        repair_attempted=state.get("repair_attempted", False),
        latency_ms=state.get("latency_ms"),
    )


@app.post("/schema/reindex", response_model=ReindexResponse)
def reindex() -> ReindexResponse:
    try:
        stats = rebuild_schema_index()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return ReindexResponse(tables_indexed=stats["tables_indexed"], restricted_columns=stats["restricted_columns"])


@app.get("/audit/{request_id}", response_model=AuditRecordResponse)
def audit(request_id: str) -> AuditRecordResponse:
    record = find_audit_record(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No audit record found for request_id={request_id!r}")

    return AuditRecordResponse(**record)
