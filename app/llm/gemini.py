"""
Gemini provider (default). Verified against Google's own docs as of
Aug 2026 (ai.google.dev/gemini-api/docs/models, .../pricing): the Flash
family has a genuine free tier, no credit card required. gemini-3.6-flash
is the current stable, free-tier Flash model -- avoid gemini-2.5-flash,
which Google has scheduled for shutdown on 2026-10-16. Re-verify before
changing LLM_MODEL, since Google's free-tier lineup rotates every few
months and deprecates older Flash generations with short notice
(gemini-2.0-flash was retired 2026-06-01).
"""

from __future__ import annotations

from app.core.config import settings
from app.llm.base import LLMProvider, LLMProviderError


class GeminiProvider(LLMProvider):
    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise LLMProviderError(
                "GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey "
                "and set it in .env, or switch LLM_PROVIDER to 'groq' or 'ollama'."
            )

        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        self._genai = genai
        self._model_name = settings.llm_model

    def _complete_once(self, system: str, user: str, json_mode: bool = False) -> str:
        model = self._genai.GenerativeModel(
            model_name=self._model_name,
            system_instruction=system,
        )

        generation_config: dict = {"temperature": 0}
        if json_mode:
            generation_config["response_mime_type"] = "application/json"

        response = model.generate_content(user, generation_config=generation_config)

        if not response.candidates:
            reason = getattr(response.prompt_feedback, "block_reason", "unknown")
            raise LLMProviderError(f"Gemini returned no candidates (block_reason={reason})")

        return response.text
