"""
Structured audit logging (spec section 21).

Two sinks for every audit record:
    1. stdout, via the standard `logging` module -- composes with
       whatever log aggregation the deployment already has (Docker
       logs locally, any log shipper in a real deployment).
    2. data/audit_log.jsonl -- a simple append-only local file, so
       GET /audit/{request_id} (Stage 7) can look up a specific past
       record without adding a database table or a dependency like
       Redis (out of scope per spec section 28). This is a deliberate
       "simple architecture" choice: fine for a portfolio-scale
       project, and explicitly not claimed to be a production log
       store -- see the README's Limitations section.

Deliberately logs metadata, never raw sensitive content:
    - NOT logged: generated SQL text (may contain literal values from
      the question), row data (actual customer/business data).
    - Logged: sql_metadata (tables/joins/query_type -- structural, not
      data), guard verdicts (pass/fail + which table/column NAMES were
      involved, never the underlying data), row COUNT (not content).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading

from app.core.config import settings

_LOGGER_NAME = "text2sql.audit"
_AUDIT_FILE_PATH = os.path.join(os.path.dirname(settings.policy_path), "audit_log.jsonl")
_file_lock = threading.Lock()


def get_audit_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(settings.log_level)
        logger.propagate = False
    return logger


def write_audit_record(record: dict) -> None:
    """Log to stdout AND append to the local JSONL file used by GET /audit/{id}."""
    line = json.dumps(record, default=str)
    get_audit_logger().info(line)

    with _file_lock:
        os.makedirs(os.path.dirname(_AUDIT_FILE_PATH), exist_ok=True)
        with open(_AUDIT_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def find_audit_record(request_id: str) -> dict | None:
    """
    Linear scan of the JSONL file for a matching request_id, most recent
    first. Fine at this project's scale (a local demo/eval log, not a
    production audit trail with millions of rows) -- see README
    Limitations for the honest caveat about this not being how you'd
    do it at real scale (you'd use a real audit-log table/store).
    """
    if not os.path.exists(_AUDIT_FILE_PATH):
        return None

    with _file_lock, open(_AUDIT_FILE_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("request_id") == request_id:
            return record

    return None
