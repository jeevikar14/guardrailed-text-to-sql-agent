"""
Tests for app.guards.complexity_guard. No database or LLM needed.
"""

from app.guards.complexity_guard import check_complexity
from app.guards.sql_analysis import parse_sql


def _check(sql: str):
    return check_complexity(parse_sql(sql))


class TestLimitEnforcement:
    def test_pure_aggregate_needs_no_limit(self):
        assert _check("SELECT AVG(price) FROM products").is_pass()

    def test_wrapped_aggregate_needs_no_limit(self):
        assert _check("SELECT ROUND(AVG(price), 2) FROM products").is_pass()

    def test_multiple_aggregates_need_no_limit(self):
        assert _check("SELECT COUNT(*), SUM(price) FROM products").is_pass()

    def test_grouped_aggregate_without_limit_fails(self):
        # A GROUP BY can still return many rows -- must require LIMIT.
        result = _check("SELECT region, COUNT(*) FROM customers GROUP BY region")
        assert not result.is_pass()

    def test_grouped_aggregate_with_limit_passes(self):
        assert _check("SELECT region, COUNT(*) FROM customers GROUP BY region LIMIT 50").is_pass()

    def test_plain_listing_without_limit_fails(self):
        result = _check("SELECT id, name FROM customers")
        assert not result.is_pass()

    def test_plain_listing_with_limit_passes(self):
        assert _check("SELECT id, name FROM customers LIMIT 50").is_pass()

    def test_mixed_raw_column_without_limit_fails(self):
        # A raw column alongside no GROUP BY is not a bounded aggregate.
        result = _check("SELECT price, name FROM products")
        assert not result.is_pass()

    def test_complexity_violations_are_repairable(self):
        result = _check("SELECT id, name FROM customers")
        assert result.repairable is True


class TestSelectStar:
    def test_select_star_always_fails_even_with_limit(self):
        result = _check("SELECT * FROM customers LIMIT 10")
        assert not result.is_pass()
        assert "SELECT *" in result.reason


class TestJoinAndSubqueryLimits:
    def test_within_join_limit_passes(self):
        sql = (
            "SELECT o.id FROM orders o "
            "JOIN order_items oi ON oi.order_id=o.id "
            "JOIN customers c ON c.id=o.customer_id LIMIT 10"
        )
        assert _check(sql).is_pass()

    def test_exceeding_join_limit_fails(self):
        # max_joins defaults to 3 -- 4 joins (5 tables) must fail.
        sql = (
            "SELECT o.id FROM orders o "
            "JOIN order_items oi ON oi.order_id=o.id "
            "JOIN customers c ON c.id=o.customer_id "
            "JOIN products p ON p.id=oi.product_id "
            "JOIN employees e ON true LIMIT 10"
        )
        result = _check(sql)
        assert not result.is_pass()
        assert "joins" in result.reason

    def test_deep_nesting_fails(self):
        sql = (
            "SELECT id FROM orders WHERE id IN ("
            "SELECT id FROM orders WHERE id IN ("
            "SELECT id FROM orders WHERE id IN ("
            "SELECT id FROM orders))) LIMIT 10"
        )
        result = _check(sql)
        assert not result.is_pass()
