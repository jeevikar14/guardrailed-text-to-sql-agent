"""
Guard 3: PII / sensitive-data protection (spec section 11).

Policy-based, as the spec requires (no Presidio, no NLP-based PII
detection). Overlaps deliberately with policy_guard: every column
policy_guard rejects for being disallowed will also be caught here if
it carries a sensitivity tag, which today is always true in
data/policies.yaml (every disallowed column is tagged PII or
CONFIDENTIAL).

The reason this is still a distinct, non-redundant guard rather than
just re-deriving policy_guard's verdict: it keys off `sensitivity`
being present, NOT off `allowed` being False. If someone edits
policies.yaml in the future and accidentally sets `allowed: true` on a
column still tagged `sensitivity: PII`, policy_guard would wrongly pass
it -- this guard still catches it. That's genuine defense in depth, not
duplicated logic wearing a different name.
"""

from __future__ import annotations

from app.core.policy_loader import get_policy
from app.guards.models import GuardResult, fail_result, pass_result
from app.guards.sql_analysis import ParsedSQL, column_table_pairs, resolve_table_aliases

GUARD_NAME = "pii"


def check_pii(parsed: ParsedSQL) -> GuardResult:
    policy = get_policy()
    alias_map = resolve_table_aliases(parsed.tree)

    sensitive_hits: list[dict] = []

    for table_ref, column in column_table_pairs(parsed.tree):
        if table_ref:
            real_table = alias_map.get(table_ref, table_ref)
            if real_table not in parsed.tables:
                continue
            sensitivity = policy.get_column_sensitivity(real_table, column)
            if sensitivity:
                sensitive_hits.append({"table": real_table, "column": column, "sensitivity": sensitivity})
        else:
            for table in parsed.tables:
                if not policy.has_column_defined(table, column):
                    continue
                sensitivity = policy.get_column_sensitivity(table, column)
                if sensitivity:
                    sensitive_hits.append({"table": table, "column": column, "sensitivity": sensitivity})

    if sensitive_hits:
        # Dedupe (a column can be reached via both a qualified and
        # unqualified path if the query is written oddly).
        seen = set()
        deduped = []
        for hit in sensitive_hits:
            key = (hit["table"], hit["column"])
            if key not in seen:
                seen.add(key)
                deduped.append(hit)

        summary = ", ".join(f"{h['table']}.{h['column']} ({h['sensitivity']})" for h in deduped)
        return fail_result(
            GUARD_NAME,
            f"Query accesses sensitive data: {summary}.",
            repairable=False,
            sensitive_columns=deduped,
        )

    return pass_result(GUARD_NAME)
