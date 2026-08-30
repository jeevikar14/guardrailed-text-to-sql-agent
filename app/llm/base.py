"""
LLM provider abstraction.

Every provider (Gemini, Groq, Ollama) implements the same narrow
interface: `_complete_once(system, user, json_mode)`. Everything else --
retries, JSON extraction/parsing -- lives here once, so provider modules
stay thin and swapping LLM_PROVIDER in .env never requires touching
calling code in app.llm.prompts or app.agent.nodes.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from functools import lru_cache

from app.core.config import settings


class LLMProviderError(Exception):
    """Raised when an LLM provider fails after all retries, or is misconfigured."""


class LLMOutputParseError(Exception):
    """Raised when a provider's response can't be parsed as the expected JSON shape."""


class LLMProvider(ABC):
    """
    Base class for all LLM providers.

    Subclasses implement `_complete_once`; callers use `complete()` /
    `complete_json()`, which add retry-on-transient-failure behavior on
    top of the provider-specific call.
    """

    max_retries: int = 2
    retry_backoff_seconds: float = 1.0

    @abstractmethod
    def _complete_once(self, system: str, user: str, json_mode: bool = False) -> str:
        """Provider-specific single completion call. Returns raw text."""
        raise NotImplementedError

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        """Text completion with automatic retry on transient failures."""
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._complete_once(system, user, json_mode=json_mode)
            except Exception as e:  # noqa: BLE001 - intentionally broad, we wrap and re-raise
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
        raise LLMProviderError(
            f"{self.__class__.__name__} failed after {self.max_retries + 1} attempt(s): {last_err}"
        ) from last_err

    def complete_json(self, system: str, user: str) -> dict:
        """
        Completion that expects a single JSON object back. Handles the common
        failure modes of LLMs asked to "return only JSON": markdown code
        fences, leading/trailing prose the model added anyway, etc.
        """
        raw = self.complete(system, user, json_mode=True)
        return extract_json_object(raw)


def extract_json_object(text: str) -> dict:
    """
    Robustly extract a JSON object from an LLM response that is *supposed*
    to be pure JSON but might be wrapped in ```json fences or have stray
    prose around it.
    """
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMOutputParseError(f"No JSON object found in LLM response: {text[:200]!r}")

    candidate = cleaned[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise LLMOutputParseError(
            f"LLM response looked like JSON but failed to parse: {e}. Raw: {text[:200]!r}"
        ) from e


@lru_cache
def get_llm_provider() -> LLMProvider:
    """
    Cached factory: returns the configured provider as a singleton, so the
    SDK client (and any connection pooling it does) is reused across agent
    node calls instead of reconstructed per-request.
    """
    provider = settings.llm_provider

    if provider == "gemini":
        from app.llm.gemini import GeminiProvider

        return GeminiProvider()
    if provider == "groq":
        from app.llm.groq import GroqProvider

        return GroqProvider()
    if provider == "ollama":
        from app.llm.ollama import OllamaProvider

        return OllamaProvider()

    raise LLMProviderError(
        f"Unknown LLM_PROVIDER '{provider}'. Expected one of: gemini, groq, ollama."
    )
