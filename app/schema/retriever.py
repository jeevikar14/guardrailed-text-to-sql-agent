"""
Semantic schema retrieval.

Given a natural-language question, returns only the relevant tables
(not the whole database schema) as hydrated TableMetadata objects, ready
to hand to the SQL generation prompt (Stage 3).

Design: ChromaDB is only used for ranking (which table names are most
relevant); the actual structured metadata returned comes from
`data/schema_metadata.json` via app.schema.indexer.load_schema_metadata,
so the retriever never returns partial/denormalized data.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schema.embeddings import embed_text
from app.schema.indexer import default_schema_metadata_path, get_client, get_collection, load_schema_metadata
from app.schema.metadata import SchemaMetadata, TableMetadata

DEFAULT_TOP_K = 4
# Cosine distance above which a match is considered weak. Chroma with
# hnsw:space="cosine" returns distance = 1 - cosine_similarity, so lower
# is better; 0 is a perfect match.
WEAK_MATCH_DISTANCE = 0.9


@dataclass
class RetrievedTable:
    table: TableMetadata
    distance: float


def retrieve_relevant_schema(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    schema_metadata_path: str | None = None,
) -> list[RetrievedTable]:
    """
    Return the top_k most semantically relevant tables for `query`.

    Falls back gracefully: if ChromaDB has fewer than top_k tables
    indexed, returns what's available. If the index is empty (e.g.
    `scripts/index_schema.py` hasn't been run yet), returns an empty list
    rather than raising -- callers (the intent/agent layer) are
    responsible for handling "no schema retrieved" as its own case.
    """
    client = get_client()
    collection = get_collection(client)

    if collection.count() == 0:
        return []

    query_vector = embed_text(query)
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=min(top_k, collection.count()),
    )

    table_names = results["ids"][0]
    distances = results["distances"][0]

    schema = load_schema_metadata(schema_metadata_path or default_schema_metadata_path())

    hydrated: list[RetrievedTable] = []
    for name, distance in zip(table_names, distances):
        table = schema.get_table(name)
        if table is not None:
            hydrated.append(RetrievedTable(table=table, distance=distance))

    return hydrated


def retrieve_relevant_tables(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    schema_metadata_path: str | None = None,
) -> list[TableMetadata]:
    """Convenience wrapper returning just the TableMetadata, unwrapped from distance scores."""
    return [r.table for r in retrieve_relevant_schema(query, top_k, schema_metadata_path)]


def _default_metadata_path() -> str:
    # Deprecated alias -- kept only in case anything external imported
    # this private name; new code should use
    # app.schema.indexer.default_schema_metadata_path directly.
    return default_schema_metadata_path()
