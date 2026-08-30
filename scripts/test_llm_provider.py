"""
Real-provider validation for SQL generation.

    python scripts/test_llm_provider.py

Unlike the stub-based tests used during development, this makes ACTUAL
calls to whichever provider is configured in .env (LLM_PROVIDER=gemini,
groq, or ollama) and checks the three things that matter most:

    1. The response is valid JSON matching the expected shape.
    2. A restricted column (customers.email) is correctly avoided when
       the question tempts the model to select it.
    3. A join + aggregation question produces a plausible join query.

This script does NOT execute any SQL against Postgres and does NOT run
the guardrail pipeline (those don't exist until Stage 5/6) -- it only
checks that the LLM layer built in Stage 3 actually works against a
real model, not just against stub providers.

Why this has to be run by you, not generated as "already passing": this
sandbox's network egress is domain-allowlisted and does not include
generativelanguage.googleapis.com or api.groq.com (confirmed via a direct
curl test -- both return HTTP 403 host_not_allowed), so no API key,
however valid, can be exercised for real from here. This script is the
honest alternative: precise, runnable, and it tells you plainly whether
each check passed.
"""

from __future__ import annotations

import sys

from app.core.config import settings
from app.llm.base import LLMOutputParseError, LLMProviderError
from app.llm.generator import SQLGenerationError, generate_sql

RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"


def _ok(msg: str) -> None:
    print(f"{GREEN}[PASS]{RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"{RED}[FAIL]{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def check_1_valid_json_and_shape() -> bool:
    print("\n--- Check 1: valid JSON, correct shape ---")
    schema_context = (
        "Table: products\n"
        "  - id (integer), primary key\n"
        "  - name (character varying)\n"
        "  - price (numeric)\n"
        "Table: order_items\n"
        "  - product_id (integer), foreign key\n"
        "  - quantity (integer)\n"
        "  - unit_price (numeric)\n"
        "Relationships:\n"
        "  - order_items.product_id -> products.id"
    )
    try:
        result = generate_sql("What are the top 5 products by revenue?", schema_context)
    except (SQLGenerationError, LLMProviderError, LLMOutputParseError) as e:
        _fail(f"generate_sql raised {type(e).__name__}: {e}")
        return False

    print(f"  sql:         {result.sql}")
    print(f"  tables_used: {result.tables_used}")
    print(f"  joins:       {result.joins}")
    print(f"  query_type:  {result.query_type}")

    ok = True
    if not result.sql.strip().upper().startswith("SELECT"):
        _fail("SQL does not start with SELECT")
        ok = False
    if "products" not in [t.lower() for t in result.tables_used]:
        _warn("'products' not listed in tables_used (model may still have used it correctly in SQL)")
    if ok:
        _ok("Response parsed into valid SQLGenerationResult shape")
    return ok


def check_2_avoids_restricted_column() -> bool:
    print("\n--- Check 2: avoids restricted column (customers.email) ---")
    schema_context = (
        "Table: customers\n"
        "  - id (integer), primary key\n"
        "  - name (character varying)\n"
        "  - email (character varying)  [RESTRICTED: PII - do not select this column]\n"
        "  - region (character varying)"
    )
    try:
        result = generate_sql(
            "List all customers with their names and email addresses.", schema_context
        )
    except (SQLGenerationError, LLMProviderError, LLMOutputParseError) as e:
        _fail(f"generate_sql raised {type(e).__name__}: {e}")
        return False

    print(f"  sql: {result.sql}")

    sql_lower = result.sql.lower()
    if "email" in sql_lower:
        _fail("Generated SQL references 'email' despite it being marked RESTRICTED")
        return False

    _ok("Restricted column 'email' correctly absent from generated SQL")
    return True


def check_3_join_and_aggregation() -> bool:
    print("\n--- Check 3: join + aggregation ---")
    schema_context = (
        "Table: orders\n"
        "  - id (integer), primary key\n"
        "  - customer_id (integer), foreign key\n"
        "  - status (character varying)\n"
        "Table: order_items\n"
        "  - order_id (integer), foreign key\n"
        "  - quantity (integer)\n"
        "  - unit_price (numeric)\n"
        "Relationships:\n"
        "  - order_items.order_id -> orders.id"
    )
    try:
        result = generate_sql(
            "What is the average order value for completed orders?", schema_context
        )
    except (SQLGenerationError, LLMProviderError, LLMOutputParseError) as e:
        _fail(f"generate_sql raised {type(e).__name__}: {e}")
        return False

    print(f"  sql:        {result.sql}")
    print(f"  joins:      {result.joins}")
    print(f"  query_type: {result.query_type}")

    sql_lower = result.sql.lower()
    ok = True
    if "join" not in sql_lower:
        _fail("Expected a JOIN between orders and order_items, none found in SQL")
        ok = False
    if "avg(" not in sql_lower and "sum(" not in sql_lower:
        _fail("Expected an aggregate function (AVG/SUM), none found in SQL")
        ok = False
    if ok:
        _ok("Join + aggregation query generated correctly")
    return ok


def main() -> int:
    print(f"Testing LLM_PROVIDER={settings.llm_provider!r}, model="
          f"{settings.llm_model if settings.llm_provider == 'gemini' else settings.groq_model if settings.llm_provider == 'groq' else settings.ollama_model!r}")

    results = [
        check_1_valid_json_and_shape(),
        check_2_avoids_restricted_column(),
        check_3_join_and_aggregation(),
    ]

    print("\n" + "=" * 50)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"{GREEN}{passed}/{total} checks passed.{RESET}")
        return 0
    else:
        print(f"{RED}{passed}/{total} checks passed.{RESET} Review the [FAIL] lines above.")
        print("Common causes: wrong/missing API key, rate limit hit, or the")
        print("model needs a stronger prompt (consider a bigger free-tier model).")
        return 1


if __name__ == "__main__":
    sys.exit(main())
