"""
Shared pytest fixtures.

Not in the original file tree (which lists only the 8 test_*.py files),
but pytest fixture sharing requires one -- adding it is the standard
way to avoid copy-pasting the same setup into all 8 files, which would
itself violate the "avoid duplicated logic" code-quality requirement.

Tests that need a live Postgres connection use the `require_db` fixture,
which skips (not fails) with a clear message if the database isn't
reachable -- so `pytest` gives a useful result whether or not
`docker compose up -d postgres` has been run first, rather than a wall
of confusing connection-refused errors.

Embeddings are stubbed for ALL tests (see `patch_embeddings`, autouse)
because this test suite must run in CI/offline environments without
downloading the ~90MB sentence-transformers model or requiring network
access to huggingface.co. This deliberately means these tests do not
validate real semantic retrieval QUALITY -- only that the retrieval
pipeline is wired correctly. See scripts/test_llm_provider.py for the
one place real-model behavior is checked (and only for the LLM, not
embeddings), and the README's Limitations section for the honest
caveat about what this test suite does and doesn't prove.
"""

from __future__ import annotations

import hashlib

import pytest
import sqlalchemy


def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
    """Deterministic hash-based fake embeddings -- same text -> same
    vector always, so tests asserting on retrieval ordering are stable,
    but this is NOT semantically meaningful (see module docstring)."""
    return [[b / 255.0 for b in hashlib.sha256(t.encode()).digest()[:32]] for t in texts]


@pytest.fixture(scope="session")
def _session_monkeypatch():
    # The builtin `monkeypatch` fixture is function-scoped by design, but
    # `schema_index` below is session-scoped (building the Chroma index
    # once per test run is expensive) and needs the embedding patch
    # active from the moment it first runs -- before any single test
    # function's own function-scoped fixtures would apply. Using
    # pytest's MonkeyPatch class directly, held at session scope, is the
    # standard way to patch something for an entire session.
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="session", autouse=True)
def patch_embeddings(_session_monkeypatch):
    import app.schema.embeddings as embeddings_module
    import app.schema.indexer as indexer_module
    import app.schema.retriever as retriever_module

    _session_monkeypatch.setattr(embeddings_module, "embed_texts", _fake_embed_texts)
    _session_monkeypatch.setattr(embeddings_module, "embed_text", lambda t: _fake_embed_texts([t])[0])
    _session_monkeypatch.setattr(indexer_module, "embed_texts", _fake_embed_texts)
    _session_monkeypatch.setattr(retriever_module, "embed_text", lambda t: _fake_embed_texts([t])[0])


@pytest.fixture(scope="session")
def require_db():
    """Skip the test cleanly if Postgres isn't reachable, rather than erroring."""
    from app.core.config import settings

    try:
        engine = sqlalchemy.create_engine(settings.database_url)
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        engine.dispose()
    except Exception as e:
        pytest.skip(f"Postgres not reachable at settings.database_url ({e}); run `docker compose up -d postgres`")


@pytest.fixture(scope="session")
def schema_index(require_db):
    """Build a real schema index (fake embeddings) once per test session."""
    from app.schema.indexer import rebuild_schema_index

    stats = rebuild_schema_index()
    return stats


from app.llm.base import LLMProvider


class StubLLMProvider(LLMProvider):
    """
    A scripted LLMProvider for tests that need the agent graph to run
    without a real network call. Routes by recognizable substrings in
    the system prompt (each prompt in app.llm.prompts has a distinct
    opening sentence), same technique used during manual development
    testing of Stage 4. Actually inherits from LLMProvider (not just
    duck-typed) so it gets the real retry/JSON-extraction behavior in
    complete()/complete_json() for free -- only _complete_once() needs
    scripting.
    """

    def __init__(self, sql_response=None, intent_allowed=True, repair_response=None, answer="Here is the answer."):
        self.sql_response = sql_response or {
            "sql": "SELECT id, name FROM customers ORDER BY id LIMIT 10",
            "tables_used": ["customers"],
            "joins": 0,
            "query_type": "simple_select",
        }
        self.intent_allowed = intent_allowed
        self.repair_response = repair_response
        self.answer = answer

    def _complete_once(self, system: str, user: str, json_mode: bool = False) -> str:
        import json

        if "safety/scope classifier" in system:
            return json.dumps(
                {
                    "allowed": self.intent_allowed,
                    "category": "database_query" if self.intent_allowed else "malicious",
                    "risk": "low",
                    "reason": "stub",
                }
            )
        if "correcting a single PostgreSQL query" in system:
            return json.dumps(self.repair_response or self.sql_response)
        if "query generation engine" in system:
            return json.dumps(self.sql_response)
        if "natural-language answer" in system:
            return self.answer
        raise AssertionError(f"StubLLMProvider got an unrecognized prompt: {system[:80]!r}")


@pytest.fixture
def stub_llm(monkeypatch):
    """
    Patch get_llm_provider everywhere it's been imported with `from ...
    import get_llm_provider` (app.agent.nodes, app.llm.generator) --
    yields a factory so each test can configure its own scripted
    responses.
    """
    import app.agent.nodes as nodes_module
    import app.llm.generator as generator_module

    def _make(**kwargs) -> StubLLMProvider:
        provider = StubLLMProvider(**kwargs)
        monkeypatch.setattr(nodes_module, "get_llm_provider", lambda: provider)
        monkeypatch.setattr(generator_module, "get_llm_provider", lambda: provider)
        return provider

    return _make
