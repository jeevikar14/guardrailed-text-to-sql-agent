"""
Local embedding generation via sentence-transformers.

Deliberately the ONLY place in the codebase that imports SentenceTransformer,
so swapping embedding backends later touches one file. Model loads are
lazy and cached at module level, since loading the model is expensive
(hundreds of ms to a few seconds) and it should happen once per process,
not once per request.

No network calls happen here at query time -- the model weights are
downloaded once (on first run) and cached locally by huggingface_hub /
sentence-transformers under the default cache dir. This satisfies the
"embeddings must run locally, no paid API" requirement: the one-time
weight download is free and is not a per-query network dependency.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings


@lru_cache
def _get_model():
    # Imported lazily so that anything that doesn't need embeddings
    # (e.g. running just the guards or the API health check) doesn't
    # pay the import cost of torch/transformers.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of documents. Used by the indexer when building the index."""
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_text(text: str) -> list[float]:
    """Embed a single query string. Used by the retriever at request time."""
    return embed_texts([text])[0]
