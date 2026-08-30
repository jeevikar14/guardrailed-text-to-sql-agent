"""
Rebuild the schema index end-to-end.

    python scripts/index_schema.py

Thin CLI wrapper around app.schema.indexer.rebuild_schema_index(), which
is the single implementation of "introspect -> merge policy -> save JSON
-> rebuild ChromaDB" -- POST /schema/reindex (Stage 7) calls the exact
same function, so the CLI and the API can never drift out of sync.
"""

from __future__ import annotations

import sys
import time

from app.schema.indexer import rebuild_schema_index


def main() -> int:
    print("Rebuilding schema index (introspect -> policy merge -> embed -> index)...")
    t0 = time.time()

    try:
        stats = rebuild_schema_index()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1

    elapsed = time.time() - t0
    print(f"  {stats['tables_indexed']} table(s) indexed")
    print(f"  {stats['restricted_columns']} restricted column(s) found across the schema")
    print(f"  done in {elapsed:.2f}s")
    print("\nSchema index rebuilt successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
