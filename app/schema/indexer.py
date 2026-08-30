"""
ChromaDB indexing for schema documents.

One document per table (not per column) is embedded and stored. Table
granularity keeps retrieval simple and interpretable: a user question
retrieves a small set of relevant TABLES, and the full column-level
detail (including which columns are policy-restricted) is hydrated from
`data/schema_metadata.json` afterwards by the retriever.

ChromaDB is used purely as a local, persistent, free vector index --
no network calls, no paid tier. Data lives under settings.chroma_path.
"""

from __future__ import annotations

import json

import chromadb

from app.core.config import settings
from app.schema.embeddings import embed_texts
from app.schema.metadata import SchemaMetadata, render_table_document


def get_client() -> chromadb.PersistentClient:
    # Telemetry disabled: no reason for a security-focused project to phone
    # home. Note: chromadb==0.5.11 has a known cosmetic bug where a
    # "Failed to send telemetry event" warning can still print to stderr
    # even with anonymized_telemetry=False, due to a signature mismatch
    # with its pinned posthog dependency. It's caught internally, doesn't
    # raise, and no data leaves the machine -- safe to ignore.
    return chromadb.PersistentClient(
        path=settings.chroma_path,
        settings=chromadb.config.Settings(anonymized_telemetry=False),
    )


def get_collection(client: chromadb.PersistentClient):
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )


def clear_index() -> None:
    """Delete the collection entirely, so build_index() starts from empty."""
    client = get_client()
    try:
        client.delete_collection(name=settings.chroma_collection)
    except Exception:
        # Collection may not exist yet on a fresh install -- that's fine.
        pass


def build_index(schema: SchemaMetadata) -> int:
    """
    Rebuild the ChromaDB index from scratch for the given schema metadata.

    Returns the number of tables indexed. Safe to call repeatedly (e.g.
    from POST /schema/reindex in Stage 7) -- it always clears first, so
    there's no stale/duplicate document risk.
    """
    clear_index()

    client = get_client()
    collection = get_collection(client)

    if not schema.tables:
        return 0

    ids = [t.name for t in schema.tables]
    documents = [render_table_document(t) for t in schema.tables]
    embeddings = embed_texts(documents)
    metadatas = [
        {
            "table": t.name,
            "allowed": t.allowed,
            "column_count": len(t.columns),
        }
        for t in schema.tables
    ]

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )

    return len(ids)


def default_schema_metadata_path() -> str:
    """
    Single source of truth for where schema_metadata.json lives --
    colocated with policies.yaml under data/. Both app.schema.retriever
    and scripts/index_schema.py use this instead of each hardcoding the
    path independently.
    """
    import os

    return os.path.join(os.path.dirname(settings.policy_path), "schema_metadata.json")


def rebuild_schema_index() -> dict:
    """
    Full pipeline: introspect the live DB -> merge with policy -> save
    schema_metadata.json -> rebuild the ChromaDB index. Returns summary
    stats. The ONE place this logic lives -- both scripts/index_schema.py
    and POST /schema/reindex (Stage 7) call this rather than each
    re-implementing the same four steps.
    """
    from app.core.policy_loader import get_policy
    from app.schema.introspector import introspect_schema
    from app.schema.metadata import build_schema_metadata

    raw_tables = introspect_schema()
    if not raw_tables:
        raise RuntimeError(
            "No tables found in the 'public' schema. Did the Postgres init scripts run? "
            "(docker compose down -v && docker compose up)"
        )

    policy = get_policy()
    schema = build_schema_metadata(raw_tables, policy)
    save_schema_metadata(schema, default_schema_metadata_path())
    tables_indexed = build_index(schema)
    restricted_columns = sum(len(t.restricted_columns()) for t in schema.tables)

    return {"tables_indexed": tables_indexed, "restricted_columns": restricted_columns}


def save_schema_metadata(schema: SchemaMetadata, path: str) -> None:
    """Persist SchemaMetadata as JSON -- the source of truth the retriever hydrates from."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(schema.model_dump_json(indent=2))


def load_schema_metadata(path: str) -> SchemaMetadata:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return SchemaMetadata.model_validate(raw)
