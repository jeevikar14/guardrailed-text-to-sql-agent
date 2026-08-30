"""
Shared types for the guardrail pipeline.

Every guard (ast_guard, policy_guard, pii_guard, complexity_guard,
function_guard) returns a GuardResult. The agent (Stage 4) accumulates
these into AgentState.guard_results, and the audit log persists them
verbatim -- this is the one shape everything downstream depends on.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class GuardStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class GuardResult(BaseModel):
    guard_name: str
    status: GuardStatus
    reason: str | None = None
    # True only for failures the repair loop (Stage 6) is allowed to
    # attempt fixing (syntax errors, invalid column/table references).
    # Security-relevant failures (policy, PII, dangerous function, severe
    # complexity) MUST be repairable=False -- the repair loop trusts this
    # flag without re-deriving it, so getting it wrong here is a real
    # security bug, not a UX inconvenience.
    repairable: bool = False
    # Free-form structured detail for audit logging (e.g. which tables/
    # columns were involved) -- never raw SQL literals or secrets.
    metadata: dict = Field(default_factory=dict)

    def is_pass(self) -> bool:
        return self.status == GuardStatus.PASS


def pass_result(guard_name: str, **metadata) -> GuardResult:
    return GuardResult(guard_name=guard_name, status=GuardStatus.PASS, metadata=metadata)


def fail_result(guard_name: str, reason: str, *, repairable: bool, **metadata) -> GuardResult:
    return GuardResult(
        guard_name=guard_name,
        status=GuardStatus.FAIL,
        reason=reason,
        repairable=repairable,
        metadata=metadata,
    )
