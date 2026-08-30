"""
Loads and caches data/policies.yaml.

This is intentionally the SINGLE place that reads the policy file.
Both app.schema.metadata (to annotate schema docs for retrieval/prompting)
and app.guards.policy_guard / pii_guard (Stage 5, to actually enforce
access control on generated SQL) import from here. This avoids two
independent YAML parsers drifting out of sync with each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from app.core.config import settings


@dataclass(frozen=True)
class ColumnPolicy:
    allowed: bool
    sensitivity: str | None = None


@dataclass(frozen=True)
class TablePolicy:
    allowed: bool
    columns: dict[str, ColumnPolicy] = field(default_factory=dict)


@dataclass(frozen=True)
class Policy:
    tables: dict[str, TablePolicy]
    denied_functions: frozenset[str]
    sensitivity_categories: frozenset[str]

    def is_table_allowed(self, table: str) -> bool:
        """Default-deny: a table not listed in the policy is NOT allowed."""
        t = self.tables.get(table.lower())
        return bool(t and t.allowed)

    def is_column_allowed(self, table: str, column: str) -> bool:
        """Default-deny: an unlisted table or column is NOT allowed."""
        t = self.tables.get(table.lower())
        if not t or not t.allowed:
            return False
        c = t.columns.get(column.lower())
        return bool(c and c.allowed)

    def has_column_defined(self, table: str, column: str) -> bool:
        """
        Whether `column` is a literal, known column of `table` per the
        policy file -- regardless of whether it's allowed. Used by
        policy_guard to distinguish "this is a real, restricted column"
        from "this identifier is an output alias / not a real column at
        all" (e.g. `ORDER BY total_revenue` where total_revenue is a
        SELECT-list alias, not a physical column) -- the latter must
        never be treated as a policy violation.
        """
        t = self.tables.get(table.lower())
        return bool(t and column.lower() in t.columns)

    def get_column_sensitivity(self, table: str, column: str) -> str | None:
        t = self.tables.get(table.lower())
        if not t:
            return None
        c = t.columns.get(column.lower())
        return c.sensitivity if c else None

    def is_function_denied(self, function_name: str) -> bool:
        return function_name.lower() in self.denied_functions


def _parse_policy(raw: dict) -> Policy:
    tables: dict[str, TablePolicy] = {}
    for table_name, table_def in (raw.get("tables") or {}).items():
        columns: dict[str, ColumnPolicy] = {}
        for col_name, col_def in (table_def.get("columns") or {}).items():
            columns[col_name.lower()] = ColumnPolicy(
                allowed=bool(col_def.get("allowed", False)),
                sensitivity=col_def.get("sensitivity"),
            )
        tables[table_name.lower()] = TablePolicy(
            allowed=bool(table_def.get("allowed", False)),
            columns=columns,
        )

    return Policy(
        tables=tables,
        denied_functions=frozenset(
            f.lower() for f in (raw.get("denied_functions") or [])
        ),
        sensitivity_categories=frozenset(raw.get("sensitivity_categories") or []),
    )


@lru_cache
def get_policy() -> Policy:
    """
    Cached policy accessor. Call `get_policy.cache_clear()` after editing
    policies.yaml at runtime (e.g. in tests) if you need a fresh read.
    """
    with open(settings.policy_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _parse_policy(raw)
