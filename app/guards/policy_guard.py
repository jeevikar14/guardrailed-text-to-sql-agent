"""
Guard 2: Schema / column policy (spec section 10).

Resolves every column reference in the parsed query -- qualified
(`p.name` -> `products.name` via alias resolution) and unqualified
(bare `salary`, matched against the real tables the query touches) --
and checks each against data/policies.yaml via app.core.policy_loader.
Any disallowed table or column REJECTS the query outright. This guard
never asks the LLM to "work around" a violation -- that's explicitly
out of scope per the spec.
"""

from __future__ import annotations

from app.core.policy_loader import get_policy
from app.guards.models import GuardResult, fail_result, pass_result
from app.guards.sql_analysis import ParsedSQL, column_table_pairs, resolve_table_aliases

GUARD_NAME = "policy"


def check_policy(parsed: ParsedSQL) -> GuardResult:
    policy = get_policy()

    # 1) Table-level check: every table referenced must be policy-allowed.
    disallowed_tables = sorted(t for t in parsed.tables if not policy.is_table_allowed(t))
    if disallowed_tables:
        return fail_result(
            GUARD_NAME,
            f"Query references restricted table(s): {', '.join(disallowed_tables)}.",
            repairable=False,
            tables=disallowed_tables,
        )

    # 2) Column-level check, using alias resolution for qualified columns
    #    and a conservative real-table match for unqualified ones.
    alias_map = resolve_table_aliases(parsed.tree)
    violations: list[str] = []

    for table_ref, column in column_table_pairs(parsed.tree):
        if table_ref:
            real_table = alias_map.get(table_ref, table_ref)
            if real_table in parsed.tables and not policy.is_column_allowed(real_table, column):
                violations.append(f"{real_table}.{column}")
        else:
            # Unqualified column: only a violation if it's a genuine,
            # defined column of one of the query's real tables AND
            # disallowed there. This deliberately does not flag output
            # aliases (e.g. `ORDER BY total_revenue`) as violations --
            # `total_revenue` isn't a defined column of any real table,
            # so has_column_defined() correctly returns False for it.
            for table in parsed.tables:
                if policy.has_column_defined(table, column) and not policy.is_column_allowed(
                    table, column
                ):
                    violations.append(f"{table}.{column}")

    if violations:
        # Dedupe while preserving a stable, sorted order for audit logs.
        violations = sorted(set(violations))
        return fail_result(
            GUARD_NAME,
            f"Query references restricted column(s): {', '.join(violations)}.",
            repairable=False,
            columns=violations,
        )

    return pass_result(GUARD_NAME, tables=sorted(parsed.tables))
