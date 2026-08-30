"""
Groq provider. Free developer tier, OpenAI-compatible chat completions API,
runs open-weight models on Groq's LPU hardware (very low latency).

Note: Groq deprecated `llama-3.1-8b-instant` in June 2026 in favor of
`openai/gpt-oss-20b` (see https://console.groq.com/docs/deprecations).
Verify current free-tier model availability there before changing
GROQ_MODEL.
"""

from __future__ import annotations

from app.core.config import settings
from app.llm.base import LLMProvider, LLMProviderError


class GroqProvider(LLMProvider):
    def __init__(self) -> None:
        if not settings.groq_api_key:
            raise LLMProviderError(
                "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys "
                "and set it in .env, or switch LLM_PROVIDER to 'gemini' or 'ollama'."
            )

        from groq import Groq

        self._client = Groq(api_key=settings.groq_api_key)
        self._model_name = settings.groq_model

    def _complete_once(self, system: str, user: str, json_mode: bool = False) -> str:
        kwargs: dict = {}
        if json_mode:
            # Groq's OpenAI-compatible JSON mode requires the word "json"
            # to appear somewhere in the prompt -- the shared prompt
            # templates in app.llm.prompts always include it, but this
            # guards against a future template edit forgetting it.
            kwargs["response_format"] = {"type": "json_object"}
            if "json" not in system.lower() and "json" not in user.lower():
                user = user + "\n\nRespond with a valid JSON object."

        response = self._client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            **kwargs,
        )

        choice = response.choices[0]
        content = choice.message.content
        if not content:
            raise LLMProviderError(
                f"Groq returned empty content (finish_reason={choice.finish_reason})"
            )
        return content
