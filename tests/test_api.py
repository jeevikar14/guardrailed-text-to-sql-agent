"""
Tests for app.api.routes (FastAPI). Uses TestClient (in-process, no
real network) plus schema_index and stub_llm fixtures from conftest.py.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.routes import app


@pytest.fixture
def client(schema_index):
    return TestClient(app)


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["schema_index_ready"] is True


class TestQuery:
    def test_successful_query(self, client, stub_llm):
        stub_llm(sql_response={
            "sql": "SELECT id, name FROM customers ORDER BY id LIMIT 5",
            "tables_used": ["customers"], "joins": 0, "query_type": "simple_select",
        })
        r = client.post("/query", json={"question": "list some customers"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "SUCCESS"
        assert body["row_count"] == 5
        assert len(body["guardrails"]) == 5  # ast, function, policy, pii, complexity

    def test_blocked_query_shows_guard_and_reason(self, client, stub_llm):
        stub_llm(sql_response={
            "sql": "SELECT salary FROM employees LIMIT 10",
            "tables_used": ["employees"], "joins": 0, "query_type": "simple_select",
        })
        r = client.post("/query", json={"question": "show me employee salaries"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "BLOCKED"
        assert body["blocked_guard"] is not None
        assert body["error"] is not None
        # Blocked responses must never carry rows or SQL out to the client.
        assert body["rows"] is None
        assert body["sql"] is None

    def test_empty_question_is_rejected(self, client):
        r = client.post("/query", json={"question": ""})
        assert r.status_code == 422

    def test_missing_question_field_is_rejected(self, client):
        r = client.post("/query", json={})
        assert r.status_code == 422


class TestAudit:
    def test_audit_record_retrievable_after_query(self, client, stub_llm):
        stub_llm(sql_response={
            "sql": "SELECT id FROM customers LIMIT 5",
            "tables_used": ["customers"], "joins": 0, "query_type": "simple_select",
        })
        query_response = client.post("/query", json={"question": "list customers"}).json()
        request_id = query_response["request_id"]

        r = client.get(f"/audit/{request_id}")
        assert r.status_code == 200
        assert r.json()["request_id"] == request_id
        assert r.json()["final_status"] == "SUCCESS"

    def test_audit_record_never_contains_raw_sql_or_rows(self, client, stub_llm):
        stub_llm(sql_response={
            "sql": "SELECT id FROM customers LIMIT 5",
            "tables_used": ["customers"], "joins": 0, "query_type": "simple_select",
        })
        query_response = client.post("/query", json={"question": "list customers"}).json()
        r = client.get(f"/audit/{query_response['request_id']}")
        body = r.json()
        assert "rows" not in body
        # sql_metadata (tables/joins/query_type) is fine; raw SQL text is not.
        assert "sql" not in body or body.get("sql") is None

    def test_nonexistent_audit_record_returns_404(self, client):
        r = client.get("/audit/does-not-exist-at-all")
        assert r.status_code == 404


class TestReindex:
    def test_reindex_returns_table_count(self, client):
        r = client.post("/schema/reindex")
        assert r.status_code == 200
        body = r.json()
        assert body["tables_indexed"] == 5
        assert body["restricted_columns"] == 4
