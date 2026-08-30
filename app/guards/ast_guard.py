"""
Guard 1: AST / Syntax validation.

Verifies (via app.guards.sql_analysis, built on sqlglot) that the
generated SQL is exactly one syntactically valid, read-only SELECT
statement with no mutation hidden anywhere in the tree -- top level,
inside a CTE, or inside a subquery -- and no SELECT INTO or locking
clause. This is a purely structural check: it does NOT know about
table/column policy (policy_guard) or sensitivity (pii_guard).
"""

from __future__ import annotations

from app.guards.models import GuardResult, fail_result, pass_result
from app.guards.sql_analysis import ParsedSQL, SQLParseError, parse_sql

GUARD_NAME = "ast"


def validate_ast(sql: str) -> tuple[GuardResult, ParsedSQL | None]:
    """
    Returns (GuardResult, ParsedSQL | None). ParsedSQL is None on FAIL --
    callers (policy_guard, pii_guard, complexity_guard) should only run
    if this guard PASSed, since they all depend on a valid parse.
    """
    try:
        parsed = parse_sql(sql)
    except SQLParseError as e:
        # A syntax error or multi-statement input is exactly the kind of
        # mistake the repair loop (Stage 6) can plausibly fix by asking
        # the model to try again -- it's not a security violation.
        return fail_result(GUARD_NAME, str(e), repairable=True), None

    if not parsed.is_top_level_read_only:
        return (
            fail_result(
                GUARD_NAME,
                "Top-level statement is not a SELECT/UNION query "
                f"(found: {', '.join(parsed.mutation_nodes) or 'unrecognized statement'}).",
                repairable=False,
                mutation_nodes=parsed.mutation_nodes,
            ),
            None,
        )

    if parsed.mutation_nodes:
        # Top level looked like SELECT, but a mutation is hiding inside
        # a CTE or subquery (e.g. `WITH x AS (DELETE ... RETURNING *) ...`).
        return (
            fail_result(
                GUARD_NAME,
                f"Data-modifying operation found inside the query: {', '.join(parsed.mutation_nodes)}.",
                repairable=False,
                mutation_nodes=parsed.mutation_nodes,
            ),
            None,
        )

    if parsed.has_select_into:
        return (
            fail_result(
                GUARD_NAME,
                "SELECT INTO is not allowed (creates a new table as a side effect).",
                repairable=False,
            ),
            None,
        )

    if parsed.has_locking_clause:
        return (
            fail_result(
                GUARD_NAME,
                "Locking clauses (FOR UPDATE / FOR SHARE) are not allowed on a read-only connection.",
                repairable=False,
            ),
            None,
        )

    return (
        pass_result(GUARD_NAME, tables=sorted(parsed.tables), joins=parsed.join_count),
        parsed,
    )
