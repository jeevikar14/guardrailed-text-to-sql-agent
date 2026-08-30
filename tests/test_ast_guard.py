"""
Tests for app.guards.ast_guard (and app.guards.sql_analysis, which it's
built on). No database or LLM needed -- pure SQL-string-in, GuardResult-out.
"""

from app.guards.ast_guard import validate_ast


def _assert_pass(sql: str):
    result, parsed = validate_ast(sql)
    assert result.is_pass(), f"expected PASS, got FAIL: {result.reason}"
    assert parsed is not None
    return parsed


def _assert_fail(sql: str, *, repairable: bool | None = None):
    result, parsed = validate_ast(sql)
    assert not result.is_pass(), f"expected FAIL, got PASS for: {sql}"
    assert parsed is None
    if repairable is not None:
        assert result.repairable is repairable, (
            f"expected repairable={repairable}, got {result.repairable} for: {sql}"
        )
    return result


class TestAllowedQueries:
    def test_simple_select(self):
        _assert_pass("SELECT id, name FROM customers LIMIT 10")

    def test_join_and_aggregation(self):
        _assert_pass(
            "SELECT p.name, SUM(oi.quantity*oi.unit_price) FROM products p "
            "JOIN order_items oi ON oi.product_id = p.id GROUP BY p.name LIMIT 5"
        )

    def test_subquery(self):
        _assert_pass("SELECT * FROM customers WHERE id IN (SELECT customer_id FROM orders) LIMIT 10")

    def test_cte_select_only(self):
        _assert_pass("WITH recent AS (SELECT * FROM orders) SELECT * FROM recent LIMIT 10")

    def test_union(self):
        _assert_pass("SELECT id FROM customers UNION SELECT id FROM employees")


class TestBlockedMutations:
    def test_delete(self):
        _assert_fail("DELETE FROM customers WHERE id = 1", repairable=False)

    def test_drop_table(self):
        _assert_fail("DROP TABLE customers", repairable=False)

    def test_update(self):
        _assert_fail("UPDATE employees SET salary = 0", repairable=False)

    def test_insert(self):
        _assert_fail("INSERT INTO customers (name) VALUES ('x')", repairable=False)

    def test_truncate(self):
        _assert_fail("TRUNCATE TABLE customers", repairable=False)

    def test_alter(self):
        _assert_fail("ALTER TABLE customers ADD COLUMN x int", repairable=False)

    def test_grant(self):
        _assert_fail("GRANT SELECT ON customers TO joe", repairable=False)

    def test_revoke(self):
        _assert_fail("REVOKE SELECT ON customers FROM joe", repairable=False)

    def test_create_table(self):
        _assert_fail("CREATE TABLE hacked (id int)", repairable=False)

    def test_data_modifying_cte(self):
        _assert_fail(
            "WITH deleted AS (DELETE FROM customers RETURNING *) SELECT * FROM deleted",
            repairable=False,
        )

    def test_select_into(self):
        _assert_fail("SELECT * INTO backup_table FROM customers", repairable=False)

    def test_locking_clause(self):
        _assert_fail("SELECT * FROM customers FOR UPDATE", repairable=False)


class TestStructuralRejections:
    def test_multiple_statements(self):
        # Multi-statement chaining is treated as repairable -- the model
        # most likely produced a formatting mistake, not malicious intent;
        # if repair regenerates another multi-statement or mutating query,
        # the re-run guards catch it fresh and it becomes non-repairable.
        _assert_fail("SELECT id FROM customers; DROP TABLE customers;", repairable=True)

    def test_syntax_error(self):
        _assert_fail("SELCT id FORM customers", repairable=True)

    def test_empty_string(self):
        _assert_fail("", repairable=True)

    def test_not_sql_at_all(self):
        _assert_fail("this is not sql at all", repairable=True)


class TestParsedSQLExtraction:
    def test_tables_extracted(self):
        parsed = _assert_pass("SELECT id FROM customers LIMIT 5")
        assert parsed.tables == {"customers"}

    def test_join_count(self):
        parsed = _assert_pass(
            "SELECT o.id FROM orders o JOIN customers c ON c.id = o.customer_id LIMIT 5"
        )
        assert parsed.join_count == 1

    def test_dangerous_function_detected_in_parse(self):
        # ast_guard itself doesn't reject on function name (that's
        # function_guard's job) -- but the function must be extracted
        # correctly for function_guard to act on.
        parsed = _assert_pass("SELECT pg_read_file('/etc/passwd') AS x")
        assert "pg_read_file" in parsed.functions
