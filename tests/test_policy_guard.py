"""
Tests for app.guards.policy_guard. No database or LLM needed -- reads
data/policies.yaml directly via app.core.policy_loader.
"""

from app.guards.policy_guard import check_policy
from app.guards.sql_analysis import parse_sql


def _check(sql: str):
    return check_policy(parse_sql(sql))


class TestAllowedColumns:
    def test_allowed_columns_pass(self):
        assert _check("SELECT id, name, region FROM customers").is_pass()

    def test_allowed_employee_columns_pass(self):
        assert _check("SELECT name, department FROM employees").is_pass()

    def test_order_by_alias_is_not_a_false_positive(self):
        # `total_revenue` is a SELECT-list alias, not a real column of
        # any table -- must not be mistaken for a restricted column.
        sql = (
            "SELECT p.name, SUM(oi.quantity*oi.unit_price) AS total_revenue "
            "FROM products p JOIN order_items oi ON oi.product_id=p.id "
            "GROUP BY p.name ORDER BY total_revenue DESC LIMIT 5"
        )
        assert _check(sql).is_pass()


class TestRestrictedColumns:
    def test_unqualified_restricted_column(self):
        result = _check("SELECT id, name, email FROM customers")
        assert not result.is_pass()
        assert "customers.email" in result.reason

    def test_qualified_restricted_column_via_alias(self):
        result = _check("SELECT c.id, c.email FROM customers c")
        assert not result.is_pass()
        assert "email" in result.reason

    def test_restricted_salary(self):
        result = _check("SELECT salary FROM employees")
        assert not result.is_pass()
        assert "salary" in result.reason

    def test_restricted_product_cost(self):
        result = _check("SELECT cost FROM products")
        assert not result.is_pass()

    def test_all_restricted_columns_never_pass(self):
        # Every column marked allowed: false in policies.yaml must be
        # independently confirmed blocked -- this is the full inventory,
        # not a sample, since a missed one here is a real data leak.
        restricted = [
            ("customers", "email"),
            ("customers", "phone"),
            ("products", "cost"),
            ("employees", "salary"),
        ]
        for table, column in restricted:
            result = _check(f"SELECT {column} FROM {table}")
            assert not result.is_pass(), f"{table}.{column} should be restricted but passed"

    def test_repairable_is_always_false_for_policy_violations(self):
        # Security-relevant failures must never be marked repairable --
        # this is the flag the repair loop trusts without re-deriving it.
        result = _check("SELECT email FROM customers")
        assert result.repairable is False


class TestRestrictedTables:
    def test_nonexistent_table_defaults_to_disallowed(self):
        # Default-deny: a table not listed in policies.yaml at all is
        # never allowed, even though ast_guard's parse succeeds fine.
        result = _check("SELECT * FROM pg_shadow")
        assert not result.is_pass()
