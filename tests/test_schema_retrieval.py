"""
Tests for the schema pipeline: introspector -> metadata -> indexer ->
retriever. Requires a live Postgres (skips cleanly if unavailable).
Embeddings are stubbed (see conftest.py) -- these tests validate the
pipeline's WIRING and policy annotations, not real semantic ranking
quality (that requires a real embedding model, out of scope for an
offline-runnable test suite; see scripts/test_llm_provider.py for the
one place real-model behavior is checked).
"""

from app.schema.introspector import introspect_schema
from app.schema.metadata import build_schema_metadata, render_table_document
from app.core.policy_loader import get_policy
from app.schema.retriever import retrieve_relevant_schema


class TestIntrospection:
    def test_all_tables_found(self, require_db):
        raw = introspect_schema()
        names = {t["name"] for t in raw}
        assert names == {"customers", "products", "orders", "order_items", "employees"}

    def test_primary_keys_detected(self, require_db):
        raw = introspect_schema()
        customers = next(t for t in raw if t["name"] == "customers")
        pk_columns = [c["name"] for c in customers["columns"] if c["is_primary_key"]]
        assert pk_columns == ["id"]

    def test_foreign_keys_detected(self, require_db):
        raw = introspect_schema()
        order_items = next(t for t in raw if t["name"] == "order_items")
        fk_targets = {fk["references_table"] for fk in order_items["foreign_keys"]}
        assert fk_targets == {"orders", "products"}


class TestPolicyMerge:
    def test_restricted_columns_correctly_annotated(self, require_db):
        raw = introspect_schema()
        schema = build_schema_metadata(raw, get_policy())

        customers = schema.get_table("customers")
        restricted_names = {c.name for c in customers.restricted_columns()}
        assert restricted_names == {"email", "phone"}

        employees = schema.get_table("employees")
        assert {c.name for c in employees.restricted_columns()} == {"salary"}

    def test_render_table_document_flags_restricted_columns(self, require_db):
        raw = introspect_schema()
        schema = build_schema_metadata(raw, get_policy())
        doc = render_table_document(schema.get_table("customers"))
        assert "[RESTRICTED" in doc
        assert "email" in doc  # still documented, just flagged -- not hidden entirely


class TestRetrieval:
    def test_retrieval_returns_hydrated_tables(self, schema_index):
        results = retrieve_relevant_schema("top products by revenue", top_k=3)
        assert len(results) > 0
        assert all(r.table.columns for r in results)  # fully hydrated, not just names

    def test_retrieval_respects_top_k(self, schema_index):
        results = retrieve_relevant_schema("anything", top_k=2)
        assert len(results) <= 2

    def test_empty_index_returns_empty_list_not_error(self, monkeypatch):
        # Point at an index that hasn't been built -- must degrade
        # gracefully (empty list), not raise, since the agent's
        # retrieve_schema_node handles "no results" as its own case.
        import app.schema.retriever as retriever_module

        class EmptyCollection:
            def count(self):
                return 0

        monkeypatch.setattr(retriever_module, "get_collection", lambda client: EmptyCollection())
        results = retrieve_relevant_schema("anything")
        assert results == []
