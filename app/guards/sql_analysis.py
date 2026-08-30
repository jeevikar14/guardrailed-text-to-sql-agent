"""
Shared sqlglot-based SQL parsing and structural extraction.

This is the ONE place that talks to sqlglot's AST directly. ast_guard,
policy_guard, pii_guard, and complexity_guard all call into this module
rather than re-parsing SQL or re-deriving table/column/function lists
independently -- avoids the exact kind of drift where two guards
disagree about what a query "uses".

All class names below were verified empirically against the pinned
sqlglot==25.24.5 version (not guessed from docs, which drift across
versions) -- e.g. `exp.AlterTable` does not exist in this version; the
real class is `exp.Alter`. If you upgrade sqlglot, re-verify these.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

DIALECT = "postgres"

# Every AST node type that represents a data-modifying or DDL operation.
# Checked recursively (find_all), not just at the top level, so a
# mutation hidden inside a CTE or subquery is still caught. exp.Command
# is sqlglot's fallback for syntax it doesn't have a dedicated node for
# (this is how REVOKE gets caught -- sqlglot has no exp.Revoke).
_MUTATION_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Create,
    exp.Grant,
    exp.Command,
)

# Top-level statement types that are legitimate read-only queries.
# exp.Union covers `SELECT ... UNION SELECT ...`; its branches are still
# walked for nested mutations by the mutation check above.
_READ_ONLY_TOP_LEVEL_TYPES = (exp.Select, exp.Union)


class SQLParseError(Exception):
    """Raised when SQL fails to parse, or isn't exactly one statement."""


@dataclass
class ParsedSQL:
    tree: exp.Expression
    tables: set[str] = field(default_factory=set)
    columns: set[str] = field(default_factory=set)
    functions: set[str] = field(default_factory=set)
    has_select_into: bool = False
    has_locking_clause: bool = False
    mutation_nodes: list[str] = field(default_factory=list)
    is_top_level_read_only: bool = True
    join_count: int = 0
    subquery_count: int = 0
    max_depth: int = 0


def parse_sql(sql: str) -> ParsedSQL:
    """
    Parse `sql` and extract everything the guardrail pipeline needs in
    one pass. Raises SQLParseError on invalid syntax or multi-statement
    input -- callers treat this as a repairable AST failure.
    """
    try:
        statements = sqlglot.parse(sql, dialect=DIALECT)
    except ParseError as e:
        raise SQLParseError(f"SQL syntax error: {e}") from e

    statements = [s for s in statements if s is not None]

    if len(statements) == 0:
        raise SQLParseError("No SQL statement found (empty input).")
    if len(statements) > 1:
        raise SQLParseError(
            f"Expected exactly one SQL statement, found {len(statements)} "
            "(multi-statement / semicolon-chained input is not allowed)."
        )

    tree = statements[0]

    tables = {t.name.lower() for t in tree.find_all(exp.Table) if t.name}
    columns = {c.name.lower() for c in tree.find_all(exp.Column) if c.name}
    functions = _extract_function_names(tree)

    has_select_into = isinstance(tree, exp.Select) and tree.args.get("into") is not None
    has_locking_clause = isinstance(tree, exp.Select) and bool(tree.args.get("locks"))

    mutation_nodes = [type(n).__name__ for n in tree.find_all(*_MUTATION_NODE_TYPES)]
    is_top_level_read_only = isinstance(tree, _READ_ONLY_TOP_LEVEL_TYPES)

    join_count = len(list(tree.find_all(exp.Join)))
    subqueries = list(tree.find_all(exp.Subquery))
    subquery_count = len(subqueries)
    max_depth = _max_select_depth(tree)

    return ParsedSQL(
        tree=tree,
        tables=tables,
        columns=columns,
        functions=functions,
        has_select_into=has_select_into,
        has_locking_clause=has_locking_clause,
        mutation_nodes=mutation_nodes,
        is_top_level_read_only=is_top_level_read_only,
        join_count=join_count,
        subquery_count=subquery_count,
        max_depth=max_depth,
    )


def _extract_function_names(tree: exp.Expression) -> set[str]:
    names: set[str] = set()
    for f in tree.find_all(exp.Func):
        if isinstance(f, exp.Anonymous):
            # Unknown-to-sqlglot functions (e.g. pg_read_file) parse as
            # Anonymous; sql_name() just returns "ANONYMOUS", the real
            # name lives in .this.
            name = f.this
        else:
            name = f.sql_name()
        if name:
            names.add(str(name).lower())
    return names


def _max_select_depth(tree: exp.Expression, current: int = 0) -> int:
    """
    Max nesting depth of SELECTs (subqueries + CTEs), used by the
    complexity guard. A flat query is depth 1; a subquery inside a
    subquery is depth 3, etc.
    """
    depth = current + 1 if isinstance(tree, (exp.Select, exp.Union)) else current
    child_depths = [depth]
    for child in tree.find_all(exp.Subquery, exp.CTE):
        inner = child.this
        if inner is not None:
            child_depths.append(_max_select_depth(inner, depth))
    return max(child_depths)


def resolve_table_aliases(tree: exp.Expression) -> dict[str, str]:
    """
    Map every table alias (and the table's own name, mapping to itself)
    to its real table name, lowercased. Used by policy_guard to resolve
    `p.name` -> `products.name` before checking the policy.
    """
    mapping: dict[str, str] = {}
    for t in tree.find_all(exp.Table):
        if not t.name:
            continue
        real_name = t.name.lower()
        mapping[real_name] = real_name
        if t.alias:
            mapping[t.alias.lower()] = real_name
    return mapping


def column_table_pairs(tree: exp.Expression) -> list[tuple[str | None, str]]:
    """
    Best-effort (table_alias_or_name, column_name) pairs for every
    column reference. Table resolution from aliases is intentionally
    simple (exact match on `column.table`) -- good enough for the policy
    guard's purpose, which is catching restricted columns, not full
    semantic SQL analysis.
    """
    pairs = []
    for c in tree.find_all(exp.Column):
        if c.name:
            table_ref = c.table or None
            pairs.append((table_ref.lower() if table_ref else None, c.name.lower()))
    return pairs
