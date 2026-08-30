"""
Guard 4: Query Complexity Heuristic (spec section 12).

Deliberately named a "heuristic", not a cost estimator -- this checks
simple, deterministic structural bounds (join count, subquery count,
nesting depth, presence of SELECT *, presence/absence of LIMIT) against
configurable limits in .env / app.core.config.settings. It makes no
claim about actual query execution cost, and it is not meant to.
"""

from __future__ import annotations

from sqlglot import exp

from app.core.config import settings
from app.guards.models import GuardResult, fail_result, pass_result
from app.guards.sql_analysis import ParsedSQL

GUARD_NAME = "complexity"


def check_complexity(parsed: ParsedSQL) -> GuardResult:
    violations: list[str] = []

    if parsed.join_count > settings.max_joins:
        violations.append(
            f"{parsed.join_count} joins exceeds the configured maximum of {settings.max_joins}"
        )

    if parsed.subquery_count > settings.max_subqueries:
        violations.append(
            f"{parsed.subquery_count} subqueries exceeds the configured maximum of {settings.max_subqueries}"
        )

    if parsed.max_depth > settings.max_query_depth:
        violations.append(
            f"nesting depth {parsed.max_depth} exceeds the configured maximum of {settings.max_query_depth}"
        )

    has_star = _has_select_star(parsed.tree)
    if has_star:
        violations.append("SELECT * is not allowed -- list columns explicitly")

    missing_limit = _missing_limit_on_unbounded_query(parsed)
    if missing_limit:
        violations.append(
            "query has no LIMIT and is not a single-row aggregate -- "
            f"could return an unbounded number of rows (max allowed: {settings.max_rows})"
        )

    if violations:
        # Complexity violations ARE repairable: asking the model to add a
        # LIMIT, drop SELECT *, or simplify joins is a legitimate, safe
        # repair -- unlike a security violation, nothing here exposes
        # data the model isn't allowed to see; it's purely a resource-
        # abuse concern. Still capped at the repair loop's one attempt.
        return fail_result(
            GUARD_NAME,
            "; ".join(violations),
            repairable=True,
            joins=parsed.join_count,
            subqueries=parsed.subquery_count,
            depth=parsed.max_depth,
        )

    return pass_result(
        GUARD_NAME, joins=parsed.join_count, subqueries=parsed.subquery_count, depth=parsed.max_depth
    )


def _has_select_star(tree: exp.Expression) -> bool:
    for select in tree.find_all(exp.Select):
        for projection in select.expressions:
            if isinstance(projection, exp.Star):
                return True
    return False


def _missing_limit_on_unbounded_query(parsed: ParsedSQL) -> bool:
    """
    A query needs a LIMIT unless it's a naturally-bounded aggregate: a
    top-level SELECT with no GROUP BY, that returns at most one row per
    aggregate function (e.g. `SELECT AVG(x) FROM t`). Anything else --
    plain row listings, GROUP BY (which can still return many groups),
    joins without aggregation -- must carry an explicit LIMIT.
    """
    tree = parsed.tree
    if not isinstance(tree, exp.Select):
        # Union queries: require a LIMIT to be safe, since branch sizes
        # aren't bounded here either.
        return not bool(tree.args.get("limit"))

    has_limit = tree.args.get("limit") is not None
    if has_limit:
        return False

    has_group_by = tree.args.get("group") is not None
    if has_group_by:
        # Grouped aggregates can still return many rows (one per group)
        # -- unbounded unless the guard can prove the grouping column is
        # low-cardinality, which it can't in general. Require a LIMIT.
        return True

    # No GROUP BY: safe only if EVERY selected expression is a single
    # aggregate function call (so the query can return at most one row).
    projections = tree.expressions
    all_aggregates = bool(projections) and all(
        _is_aggregate_expression(p) for p in projections
    )
    return not all_aggregates


def _is_aggregate_expression(node: exp.Expression) -> bool:
    """
    True if `node` (one SELECT projection) is safe to treat as
    contributing to a single-row result: it must contain at least one
    aggregate function, and every column reference in it must be inside
    an aggregate function's arguments (so e.g. `ROUND(AVG(x), 2)` is
    safe, but `x, SUM(y)` mixed without GROUP BY -- invalid SQL anyway,
    but we don't rely on that -- is treated conservatively as unsafe).
    """
    inner = node.this if isinstance(node, exp.Alias) else node

    agg_funcs = list(inner.find_all(exp.AggFunc))
    if not agg_funcs:
        return False

    for column in inner.find_all(exp.Column):
        if not _is_inside_any(column, agg_funcs):
            return False

    return True


def _is_inside_any(node: exp.Expression, ancestors: list[exp.Expression]) -> bool:
    # Identity comparison (not sqlglot's structural __eq__) -- two
    # distinct AggFunc nodes can be structurally equal (e.g. two
    # `SUM(quantity)` calls), so `in` would give false positives.
    ancestor_ids = {id(a) for a in ancestors}
    current = node.parent
    while current is not None:
        if id(current) in ancestor_ids:
            return True
        current = current.parent
    return False
