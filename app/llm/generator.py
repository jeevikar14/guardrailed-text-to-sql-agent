"""
SQL Generator.

Turns a natural-language question + retrieved schema context into a
typed SQLGenerationResult (SQL string + structured metadata). This is
purely a "propose" step -- it performs NO security validation itself.
The guardrail pipeline (Stage 5: AST / policy / PII / complexity guards)
is the actual enforcement point and re-validates the SQL from scratch
regardless of what this class returns.

Not in the original file tree (which lists only base/gemini/groq/
prompts.py under app/llm/) -- added because "SQL Generator" is its own
named component in the architecture (spec section 7), and giving it a
dedicated module keeps prompts.py focused on templates only, per the
project's "keep modules focused" code-quality requirement.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.llm.base import LLMOutputParseError, get_llm_provider
from app.llm.prompts import build_sql_generation_prompt

_VALID_QUERY_TYPES = {"simple_select", "aggregation", "join", "subquery"}


class SQLGenerationError(Exception):
    """
    Raised when the LLM call fails outright, or its response can't be
    parsed into the expected shape. Distinct from a guardrail rejection:
    this means "we don't even have a SQL candidate to validate."
    """


class SQLGenerationResult(BaseModel):
    sql: str
    tables_used: list[str] = Field(default_factory=list)
    joins: int = 0
    query_type: str = "simple_select"

    @field_validator("sql")
    @classmethod
    def _sql_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("LLM returned an empty SQL string")
        return v.strip()

    @field_validator("query_type")
    @classmethod
    def _normalize_query_type(cls, v: str) -> str:
        # This field is descriptive metadata (used in audit logs / UI),
        # not a security signal -- an unrecognized value from the model
        # shouldn't blow up generation, just fall back to a safe default.
        v = (v or "").strip().lower()
        return v if v in _VALID_QUERY_TYPES else "simple_select"


def generate_sql(question: str, schema_context: str) -> SQLGenerationResult:
    """
    Generate a SQL candidate for `question` given `schema_context`.

    Raises:
        SQLGenerationError: the LLM's response couldn't be parsed into the
            expected JSON shape (missing/wrong-typed fields, non-JSON output
            after all providers' JSON-mode + retry handling).
        LLMProviderError: the underlying provider call failed after retries
            (network error, missing API key, rate limit, blocked content).
            Propagates uncaught -- it's a distinct failure mode callers
            (the agent graph) need to handle separately from "the model
            responded but the response was malformed".
    """
    provider = get_llm_provider()
    system_prompt, user_prompt = build_sql_generation_prompt(question, schema_context)

    try:
        raw = provider.complete_json(system_prompt, user_prompt)
    except LLMOutputParseError as e:
        raise SQLGenerationError(f"Could not parse SQL generation response: {e}") from e

    try:
        return SQLGenerationResult.model_validate(raw)
    except ValidationError as e:
        raise SQLGenerationError(f"SQL generation response missing expected fields: {e}") from e
