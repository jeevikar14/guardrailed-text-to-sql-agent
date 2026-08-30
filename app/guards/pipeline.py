"""
Guardrail pipeline: runs all guards sequentially, exactly as the spec's
architecture diagram requires (AST -> Policy -> PII -> Complexity, never
parallel independent branches). Stops at the first failure.

Not a named file in the original spec (which lists individual guard
files under app/guards/), but the spec's own "IMPORTANT EXECUTION RULE"
(section 4) explicitly forbids implementing the guards as parallel
branches -- this module IS that sequential dependency, made concrete and
independently testable/reusable rather than re-inlined in every LangGraph
node in Stage 4 and every repair-loop retry in Stage 6.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.guards.ast_guard import validate_ast
from app.guards.complexity_guard import check_complexity
from app.guards.function_guard import check_functions
from app.guards.models import GuardResult
from app.guards.pii_guard import check_pii
from app.guards.policy_guard import check_policy
from app.guards.sql_analysis import ParsedSQL


@dataclass
class PipelineResult:
    passed: bool
    results: list[GuardResult] = field(default_factory=list)
    parsed: ParsedSQL | None = None
    # The GuardResult that stopped the pipeline, if any (== results[-1] when failed).
    failure: GuardResult | None = None


def run_guard_pipeline(sql: str) -> PipelineResult:
    """
    Run AST -> function -> policy -> PII -> complexity, in that fixed
    order, stopping at the first FAIL. Order matters for two reasons:
    (1) every later guard needs a successful parse from ast_guard, and
    (2) running function/policy/PII before complexity means a security
    violation is reported before a merely-inconvenient complexity issue,
    which is the more useful failure to surface first.
    """
    results: list[GuardResult] = []

    ast_result, parsed = validate_ast(sql)
    results.append(ast_result)
    if not ast_result.is_pass():
        return PipelineResult(passed=False, results=results, parsed=None, failure=ast_result)

    assert parsed is not None  # ast_result passed => parsed is always set

    for check in (check_functions, check_policy, check_pii, check_complexity):
        result = check(parsed)
        results.append(result)
        if not result.is_pass():
            return PipelineResult(passed=False, results=results, parsed=parsed, failure=result)

    return PipelineResult(passed=True, results=results, parsed=parsed, failure=None)
