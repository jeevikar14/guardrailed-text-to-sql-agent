"""
Public API for the LLM package.

Other packages (app.agent nodes in Stage 4, app.guards' repair loop in
Stage 6) should import from here rather than reaching into
app.llm.gemini / app.llm.groq / app.llm.ollama directly -- those are
implementation details selected by LLM_PROVIDER and swapped via
get_llm_provider(); calling code should never need to know which one
is active.

    from app.llm import generate_sql, get_llm_provider
    from app.llm import SQLGenerationResult, SQLGenerationError, LLMProviderError

Error-handling contract callers must preserve (see app.llm.generator and
app.llm.base docstrings for the full rationale):
    - LLMProviderError   -> the model call itself failed (network, auth,
                            rate limit, blocked content). Already retried
                            internally once; a further retry with the
                            SAME prompt is unlikely to help immediately.
    - SQLGenerationError -> the model responded, but not in the expected
                            shape. Not fixable by calling complete()
                            again with the same prompt -- if the agent
                            wants to recover, it needs a *different*
                            prompt. This is what the Stage 6 repair loop
                            is for.
Keeping these as two distinct exception types (rather than collapsing
both into one) is what lets the LangGraph agent route them differently:
a malformed response might be worth one repair attempt, whereas a
provider outage should surface as an ERROR status, not loop into repair.
"""

from app.llm.base import LLMOutputParseError, LLMProvider, LLMProviderError, get_llm_provider
from app.llm.generator import SQLGenerationError, SQLGenerationResult, generate_sql
from app.llm.prompts import build_sql_generation_prompt

__all__ = [
    "generate_sql",
    "SQLGenerationResult",
    "SQLGenerationError",
    "get_llm_provider",
    "LLMProvider",
    "LLMProviderError",
    "LLMOutputParseError",
    "build_sql_generation_prompt",
]
