"""
Dangerous function policy (spec section 9).

Checks every function call found anywhere in the parsed query against
`denied_functions` in data/policies.yaml (loaded once via
app.core.policy_loader, the same policy object policy_guard/pii_guard
use -- one source of truth). Deliberately configurable rather than a
giant hardcoded denylist, per the spec's explicit instruction.
"""

from __future__ import annotations

from app.core.policy_loader import get_policy
from app.guards.models import GuardResult, fail_result, pass_result
from app.guards.sql_analysis import ParsedSQL

GUARD_NAME = "function"


def check_functions(parsed: ParsedSQL) -> GuardResult:
    policy = get_policy()

    denied_found = sorted(f for f in parsed.functions if policy.is_function_denied(f))

    if denied_found:
        return fail_result(
            GUARD_NAME,
            f"Query uses disallowed function(s): {', '.join(denied_found)}.",
            repairable=False,
            functions=denied_found,
        )

    return pass_result(GUARD_NAME, functions_checked=sorted(parsed.functions))
