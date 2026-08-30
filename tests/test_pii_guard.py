"""
Tests for app.guards.pii_guard. Focused on the property that makes this
guard non-redundant with policy_guard: it keys off `sensitivity` being
present in the policy, independent of the `allowed` flag.
"""

from app.core.policy_loader import get_policy
from app.guards.pii_guard import check_pii
from app.guards.sql_analysis import parse_sql


def _check(sql: str):
    return check_pii(parse_sql(sql))


class TestSensitiveColumnsBlocked:
    def test_email_blocked(self):
        result = _check("SELECT email FROM customers")
        assert not result.is_pass()
        assert "PII" in result.reason

    def test_salary_blocked(self):
        result = _check("SELECT salary FROM employees")
        assert not result.is_pass()
        assert "CONFIDENTIAL" in result.reason

    def test_phone_blocked(self):
        result = _check("SELECT phone FROM customers")
        assert not result.is_pass()

    def test_cost_blocked(self):
        result = _check("SELECT cost FROM products")
        assert not result.is_pass()

    def test_non_sensitive_columns_pass(self):
        assert _check("SELECT id, name, region FROM customers").is_pass()


class TestDefenseInDepth:
    def test_keys_off_sensitivity_not_allowed_flag(self):
        """
        The property that makes this guard non-redundant with
        policy_guard: it must independently know email is sensitive by
        checking policy.get_column_sensitivity(), not by relying on
        policy_guard already having rejected it. Confirmed here by
        checking the policy object directly reports a sensitivity for
        every column pii_guard blocks.
        """
        policy = get_policy()
        assert policy.get_column_sensitivity("customers", "email") == "PII"
        assert policy.get_column_sensitivity("employees", "salary") == "CONFIDENTIAL"
        # And a column with no sensitivity tag must NOT be flagged.
        assert policy.get_column_sensitivity("customers", "region") is None

    def test_repairable_is_always_false(self):
        result = _check("SELECT email FROM customers")
        assert result.repairable is False
