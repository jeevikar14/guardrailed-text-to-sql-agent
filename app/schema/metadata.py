"""
Structured schema metadata models.

These models are the shared representation used across the whole schema
pipeline:

    introspector.py  -> raw dicts from Postgres
    metadata.py      -> raw dicts + policy  =>  SchemaMetadata (this file)
    indexer.py        -> SchemaMetadata      =>  ChromaDB documents
    retriever.py      -> ChromaDB hit table names => hydrated TableMetadata

`data/schema_metadata.json` is a serialized SchemaMetadata and is the
source of truth the retriever hydrates full table detail from; ChromaDB
only stores the embedding + a thin pointer (table name) for ranking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.core.policy_loader import Policy


class ForeignKeyMetadata(BaseModel):
    column: str
    references_table: str
    references_column: str


class ColumnMetadata(BaseModel):
    name: str
    data_type: str
    is_primary_key: bool = False
    is_foreign_key: bool = False
    nullable: bool = True
    allowed: bool = True
    sensitivity: Optional[str] = None
    description: Optional[str] = None


class TableMetadata(BaseModel):
    name: str
    description: Optional[str] = None
    allowed: bool = True
    columns: list[ColumnMetadata] = Field(default_factory=list)
    foreign_keys: list[ForeignKeyMetadata] = Field(default_factory=list)
    row_count_estimate: Optional[int] = None

    def allowed_columns(self) -> list[ColumnMetadata]:
        return [c for c in self.columns if c.allowed]

    def restricted_columns(self) -> list[ColumnMetadata]:
        return [c for c in self.columns if not c.allowed]


class SchemaMetadata(BaseModel):
    tables: list[TableMetadata] = Field(default_factory=list)
    generated_at: str

    def get_table(self, name: str) -> Optional[TableMetadata]:
        name = name.lower()
        for t in self.tables:
            if t.name.lower() == name:
                return t
        return None


def build_schema_metadata(
    raw_tables: list[dict],
    policy: Policy,
    table_descriptions: dict[str, str] | None = None,
    column_descriptions: dict[str, dict[str, str]] | None = None,
) -> SchemaMetadata:
    """
    Merge raw introspection output (from introspector.py) with the access
    policy (from policy_loader.py) into a single structured SchemaMetadata.

    `raw_tables` entries look like:
        {
            "name": "customers",
            "comment": "Customer records...",   # from Postgres pg_description, may be None
            "row_count_estimate": 30,
            "columns": [
                {"name": "id", "data_type": "integer", "nullable": False, "is_primary_key": True},
                ...
            ],
            "foreign_keys": [
                {"column": "customer_id", "references_table": "customers", "references_column": "id"},
            ],
        }
    """
    table_descriptions = table_descriptions or {}
    column_descriptions = column_descriptions or {}

    tables: list[TableMetadata] = []

    for raw in raw_tables:
        table_name = raw["name"]
        table_allowed = policy.is_table_allowed(table_name)

        columns: list[ColumnMetadata] = []
        for raw_col in raw["columns"]:
            col_name = raw_col["name"]
            columns.append(
                ColumnMetadata(
                    name=col_name,
                    data_type=raw_col["data_type"],
                    is_primary_key=raw_col.get("is_primary_key", False),
                    is_foreign_key=raw_col.get("is_foreign_key", False),
                    nullable=raw_col.get("nullable", True),
                    allowed=policy.is_column_allowed(table_name, col_name),
                    sensitivity=policy.get_column_sensitivity(table_name, col_name),
                    description=column_descriptions.get(table_name, {}).get(col_name),
                )
            )

        foreign_keys = [
            ForeignKeyMetadata(**fk) for fk in raw.get("foreign_keys", [])
        ]

        tables.append(
            TableMetadata(
                name=table_name,
                description=raw.get("comment") or table_descriptions.get(table_name),
                allowed=table_allowed,
                columns=columns,
                foreign_keys=foreign_keys,
                row_count_estimate=raw.get("row_count_estimate"),
            )
        )

    return SchemaMetadata(
        tables=tables,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def render_table_document(table: TableMetadata) -> str:
    """
    Render a table's metadata as a natural-language document.

    This text is what gets embedded and stored in ChromaDB, so it needs to
    describe the table well enough for semantic search to match user
    questions like "top 5 products by revenue" to the `products` and
    `order_items` tables.

    Restricted columns are still listed (so retrieval/documentation stays
    complete) but flagged, which also nudges the SQL-generation prompt
    (Stage 3) away from using them -- the policy guard (Stage 5) is the
    actual enforcement point, this is just a helpful signal upstream.
    """
    lines = [f"Table: {table.name}"]

    if table.description:
        lines.append(f"Description: {table.description}")

    if not table.allowed:
        lines.append("Access: this entire table is RESTRICTED and must not be queried.")

    lines.append("Columns:")
    for col in table.columns:
        parts = [f"{col.name} ({col.data_type})"]
        if col.is_primary_key:
            parts.append("primary key")
        if col.is_foreign_key:
            parts.append("foreign key")
        if col.description:
            parts.append(col.description)
        line = "  - " + ", ".join(parts)
        if not col.allowed:
            sensitivity = col.sensitivity or "RESTRICTED"
            line += f"  [RESTRICTED: {sensitivity} - do not select this column]"
        lines.append(line)

    if table.foreign_keys:
        lines.append("Relationships:")
        for fk in table.foreign_keys:
            lines.append(
                f"  - {table.name}.{fk.column} -> {fk.references_table}.{fk.references_column}"
            )

    return "\n".join(lines)
