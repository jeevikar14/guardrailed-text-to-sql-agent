"""
Centralized application configuration.

All environment-driven settings are defined here and nowhere else, so
every other module imports `settings` instead of calling `os.environ`
directly. This keeps configuration auditable and makes the "no hardcoded
secrets" requirement mechanically easy to verify.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # --- Database ---
    # Full-privilege connection: schema introspection / admin scripts ONLY.
    database_url: str = "postgresql://app_admin:app_admin_pw@localhost:5432/text2sql"
    # Read-only connection: the ONLY connection the Safe Executor may use.
    database_readonly_url: str = (
        "postgresql://app_readonly:app_readonly_pw@localhost:5432/text2sql"
    )

    # --- LLM provider ---
    #
    # IMPORTANT: llm_model and groq_model below are the ONLY place model
    # names should ever be written in this codebase. Nothing in app.llm.*
    # hardcodes a model string -- every provider reads settings.llm_model /
    # settings.groq_model / settings.ollama_model at call time. If you find
    # a model name hardcoded anywhere else, that's a bug: fix it to read
    # from settings instead. This makes "re-verify the free-tier model" a
    # one-line, one-file change, not a codebase-wide search.
    llm_provider: Literal["gemini", "groq", "ollama"] = "gemini"
    # Verified against Google's own docs (ai.google.dev/gemini-api/docs/models,
    # Aug 2026): gemini-3.6-flash is the current *stable* free-tier Flash
    # model. gemini-2.5-flash still works today but Google has scheduled it
    # for shutdown on 2026-10-16 -- too close to ship as a default. Re-verify
    # at https://ai.google.dev/gemini-api/docs/pricing before changing this,
    # since the free-tier lineup rotates every few months.
    llm_model: str = "gemini-3.6-flash"
    gemini_api_key: str = ""
    groq_api_key: str = ""
    # Verified against Groq's own deprecations page (console.groq.com/docs/
    # deprecations, Aug 2026): llama-3.1-8b-instant was announced deprecated
    # on 2026-06-17; Groq's official recommended replacement is
    # openai/gpt-oss-20b. Re-verify there before changing this.
    groq_model: str = "openai/gpt-oss-20b"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # --- Embeddings ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- Vector store ---
    chroma_path: str = "./data/chroma"
    chroma_collection: str = "schema_docs"

    # --- Guardrail limits ---
    max_rows: int = 100
    max_joins: int = 3
    max_subqueries: int = 2
    max_query_depth: int = 3
    query_timeout_seconds: int = 5
    db_pool_size: int = 5
    db_pool_max_overflow: int = 5

    # --- Policy ---
    policy_path: str = "./data/policies.yaml"

    # --- Streamlit ---
    backend_api_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings accessor. Use `from app.core.config import get_settings`
    rather than instantiating Settings() directly, so the whole app shares
    one parsed configuration object.
    """
    return Settings()


settings = get_settings()
