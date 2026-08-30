"""
PostgreSQL schema introspection.

Uses the ADMIN connection (settings.database_url) purely for reading
catalog metadata -- information_schema and pg_catalog -- never for
executing user-generated SQL. User queries are executed exclusively
through app.executor using the read-only role (Stage 6).
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import settings


def _get_engine() -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)


def _fetch_tables(conn) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
    ).fetchall()
    return [r[0] for r in rows]


def _fetch_columns(conn, table_name: str) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable = 'YES' AS nullable,
                COALESCE(pk.is_primary_key, FALSE) AS is_primary_key,
                COALESCE(fk.is_foreign_key, FALSE) AS is_foreign_key
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT kcu.column_name, TRUE AS is_primary_key
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                    AND tc.table_name = :table_name
                    AND tc.constraint_type = 'PRIMARY KEY'
            ) pk ON pk.column_name = c.column_name
            LEFT JOIN (
                SELECT kcu.column_name, TRUE AS is_foreign_key
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                    AND tc.table_name = :table_name
                    AND tc.constraint_type = 'FOREIGN KEY'
            ) fk ON fk.column_name = c.column_name
            WHERE c.table_schema = 'public'
              AND c.table_name = :table_name
            ORDER BY c.ordinal_position
            """
        ),
        {"table_name": table_name},
    ).mappings().fetchall()

    return [
        {
            "name": r["column_name"],
            "data_type": r["data_type"],
            "nullable": bool(r["nullable"]),
            "is_primary_key": bool(r["is_primary_key"]),
            "is_foreign_key": bool(r["is_foreign_key"]),
        }
        for r in rows
    ]


def _fetch_foreign_keys(conn, table_name: str) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT
                kcu.column_name AS column,
                ccu.table_name AS references_table,
                ccu.column_name AS references_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.table_name = :table_name
              AND tc.constraint_type = 'FOREIGN KEY'
            ORDER BY kcu.column_name
            """
        ),
        {"table_name": table_name},
    ).mappings().fetchall()

    return [
        {
            "column": r["column"],
            "references_table": r["references_table"],
            "references_column": r["references_column"],
        }
        for r in rows
    ]


def _fetch_table_comment(conn, table_name: str) -> str | None:
    row = conn.execute(
        text(
            """
            SELECT obj_description(
                (quote_ident(:table_name))::regclass, 'pg_class'
            ) AS comment
            """
        ),
        {"table_name": table_name},
    ).mappings().fetchone()
    return row["comment"] if row else None


def _fetch_row_estimate(conn, table_name: str) -> int | None:
    row = conn.execute(
        text(
            """
            SELECT reltuples::bigint AS estimate
            FROM pg_class
            WHERE relname = :table_name
            """
        ),
        {"table_name": table_name},
    ).mappings().fetchone()
    if row and row["estimate"] is not None and row["estimate"] >= 0:
        return int(row["estimate"])
    return None


def introspect_schema() -> list[dict]:
    """
    Returns raw table metadata dicts, shaped exactly as expected by
    app.schema.metadata.build_schema_metadata().

    Excludes Postgres system schemas -- only `public` (application) tables
    are ever introspected, so no internal Postgres catalog details can
    leak into schema documents or LLM prompts.
    """
    engine = _get_engine()
    raw_tables: list[dict] = []

    with engine.connect() as conn:
        table_names = _fetch_tables(conn)

        for table_name in table_names:
            raw_tables.append(
                {
                    "name": table_name,
                    "comment": _fetch_table_comment(conn, table_name),
                    "row_count_estimate": _fetch_row_estimate(conn, table_name),
                    "columns": _fetch_columns(conn, table_name),
                    "foreign_keys": _fetch_foreign_keys(conn, table_name),
                }
            )

    engine.dispose()
    return raw_tables
