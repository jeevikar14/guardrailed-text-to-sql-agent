"""
Read-only database connection management.

This module owns the ONLY SQLAlchemy engine in the codebase that is
allowed to execute guardrail-validated, LLM-generated SQL. It connects
exclusively via settings.database_readonly_url (the app_readonly role
created in database/init/03_readonly_user.sql), never
settings.database_url (the admin connection, used only by
app.schema.introspector for catalog reads).

Pooled and capped per .env (DB_POOL_SIZE / DB_POOL_MAX_OVERFLOW) so a
burst of concurrent requests can't exhaust Postgres's connection limit
-- on top of, not instead of, the CONNECTION LIMIT already set on the
role itself in 03_readonly_user.sql.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import settings


@lru_cache
def get_readonly_engine() -> Engine:
    return create_engine(
        settings.database_readonly_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_pre_ping=True,
        # Belt-and-suspenders alongside the role-level `statement_timeout`
        # set in 03_readonly_user.sql -- if that role-level default is
        # ever changed or missed on a fresh DB, this still applies.
        connect_args={
            "options": f"-c statement_timeout={settings.query_timeout_seconds * 1000}"
        },
    )
