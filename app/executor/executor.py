"""
Safe SQL Executor (spec section 14).

Executes ONLY guardrail-validated SQL, exclusively through the
read-only role's connection pool (app.executor.database). Enforces the
row cap here -- independent of whatever LIMIT the generated SQL
happens to contain -- via fetchmany(), so a query is never allowed to
pull more than settings.max_rows + 1 rows across the wire, regardless
of guard behavior upstream. This is the last line of defense before
data leaves the database.

Callers (the agent's `execute` node) are responsible for having already
run the query through app.guards.pipeline.run_guard_pipeline() and
confirmed PASS -- this module does not re-validate SQL. It does not
trust the SQL to be safe by construction either: it relies on the
read-only role's actual database privileges (see
database/init/03_readonly_user.sql) as the final enforcement layer,
exactly per the architecture's defense-in-depth principle.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as time_type
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from app.core.config import settings
from app.executor.database import get_readonly_engine


def _to_json_safe(value):
    """
    Convert a raw DB value into something json.dumps can handle directly.
    Postgres numeric -> Python Decimal, date/timestamp -> date/datetime,
    none of which are JSON-serializable by default -- and every
    downstream consumer (FastAPI response, Streamlit table, audit log)
    needs plain JSON types, so this is handled once, here, rather than
    re-solved in three different places.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time_type)):
        return value.isoformat()
    return value


@dataclass
class ExecutionResult:
    success: bool
    rows: list[dict] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str | None = None
    duration_ms: int = 0


def execute_safe_sql(sql: str) -> ExecutionResult:
    """
    Execute `sql` (already guardrail-validated) against the read-only
    role and return at most settings.max_rows rows. Never raises --
    all failure modes (timeout, permission denied, connection error)
    are captured into ExecutionResult.error with a caller-safe message;
    the underlying driver exception is never propagated raw, since it
    can echo back literal query values.
    """
    engine = get_readonly_engine()
    start = time.monotonic()

    try:
        with engine.connect() as conn:
            result_proxy = conn.execution_options(stream_results=True).execute(text(sql))
            columns = list(result_proxy.keys())
            # Fetch one more than the cap so we can tell "exactly max_rows
            # rows" apart from "truncated at max_rows" without a second
            # COUNT(*) round-trip.
            fetched = result_proxy.fetchmany(settings.max_rows + 1)
            truncated = len(fetched) > settings.max_rows
            row_slice = fetched[: settings.max_rows]
            rows = [
                {col: _to_json_safe(val) for col, val in zip(columns, row)} for row in row_slice
            ]

    except OperationalError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        message = str(getattr(e, "orig", e)).lower()
        if "statement timeout" in message or "canceling statement" in message:
            return ExecutionResult(
                success=False,
                error=f"Query exceeded the {settings.query_timeout_seconds}s timeout and was cancelled.",
                duration_ms=duration_ms,
            )
        return ExecutionResult(
            success=False,
            error="Database connection error during execution.",
            duration_ms=duration_ms,
        )

    except ProgrammingError:
        # Covers: permission denied (shouldn't happen if guards did their
        # job, but the read-only role is the real boundary if they
        # didn't), unknown table/column, type errors, etc. The raw
        # exception can echo back literal values from the query, so it
        # is deliberately not included in the user-facing message.
        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecutionResult(
            success=False,
            error="The database rejected this query. It may reference something that doesn't exist "
                  "or isn't permitted for this connection.",
            duration_ms=duration_ms,
        )

    except DBAPIError:
        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecutionResult(
            success=False,
            error="Unexpected database error during execution.",
            duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    return ExecutionResult(
        success=True,
        rows=rows,
        columns=columns,
        row_count=len(rows),
        truncated=truncated,
        duration_ms=duration_ms,
    )
