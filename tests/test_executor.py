"""
Tests for app.executor.executor / app.executor.database. Requires a
live Postgres with the app_readonly role from database/init/
03_readonly_user.sql (skips cleanly via `require_db` if unavailable).

These are the tests that prove the read-only role is a REAL security
boundary, not just documentation -- see TestReadOnlyBoundary below.
"""

import json

import pytest

from app.executor.executor import execute_safe_sql


class TestBasicExecution:
    def test_simple_select(self, require_db):
        result = execute_safe_sql("SELECT id, name, region FROM customers ORDER BY id LIMIT 5")
        assert result.success is True
        assert result.row_count == 5
        assert set(result.columns) == {"id", "name", "region"}

    def test_aggregate(self, require_db):
        result = execute_safe_sql("SELECT AVG(price) AS avg_price FROM products")
        assert result.success is True
        assert result.row_count == 1
        assert "avg_price" in result.rows[0]

    def test_nonexistent_table_fails_cleanly(self, require_db):
        result = execute_safe_sql("SELECT * FROM totally_fake_table_xyz")
        assert result.success is False
        assert result.error is not None


class TestRowCap:
    def test_result_truncated_at_max_rows(self, require_db):
        # order_items has 500+ rows seeded -- ask for far more than max_rows (100).
        result = execute_safe_sql("SELECT id FROM order_items LIMIT 100000")
        assert result.success is True
        assert result.row_count <= 100
        assert result.truncated is True

    def test_result_not_flagged_truncated_when_under_cap(self, require_db):
        result = execute_safe_sql("SELECT id FROM customers LIMIT 5")
        assert result.truncated is False


class TestJSONSafety:
    def test_decimal_and_date_values_are_json_serializable(self, require_db):
        result = execute_safe_sql(
            "SELECT AVG(price) AS avg_price, MAX(order_date) AS latest FROM products, orders"
        )
        assert result.success is True
        json.dumps(result.rows)  # must not raise


class TestReadOnlyBoundary:
    """
    The read-only role (database/init/03_readonly_user.sql) is the real
    security boundary -- these tests simulate a guard-pipeline bypass by
    calling the executor directly with a mutation, proving the DATABASE
    itself refuses it regardless of what got past the guards.
    """

    def test_delete_is_rejected_by_the_database(self, require_db):
        result = execute_safe_sql("DELETE FROM customers WHERE id = 1")
        assert result.success is False

    def test_insert_is_rejected_by_the_database(self, require_db):
        result = execute_safe_sql("INSERT INTO products (name, category, price, cost) VALUES ('x','x',1,1)")
        assert result.success is False

    def test_drop_table_is_rejected_by_the_database(self, require_db):
        result = execute_safe_sql("DROP TABLE customers")
        assert result.success is False

    def test_create_table_is_rejected_by_the_database(self, require_db):
        result = execute_safe_sql("CREATE TABLE hacked_by_test (id int)")
        assert result.success is False


@pytest.mark.slow
class TestTimeout:
    def test_long_running_query_is_cancelled(self, require_db):
        # Exceeds the configured query_timeout_seconds (default 5s) --
        # this test genuinely takes several seconds to run, which is why
        # it's marked `slow` (see pyproject.toml/README for how to skip
        # slow tests during quick local iteration: `pytest -m "not slow"`).
        result = execute_safe_sql("SELECT pg_sleep(8)")
        assert result.success is False
        assert "timeout" in (result.error or "").lower()
