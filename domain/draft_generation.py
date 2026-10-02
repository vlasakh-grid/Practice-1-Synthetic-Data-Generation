"""In-memory, foreign-key-aware draft dataset generation.

This module owns constraint-sensitive draft values and never imports a UI or
an LLM SDK.  A semantic value generator is injected so that the orchestration
is both testable and independent from Gemini.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import re
from typing import Any, Literal, Protocol

from .dependency_planner import DeferredRelationship, DependencyPlan, plan_generation
from .schema import Column, Schema, Table


class DraftGenerationError(RuntimeError):
    """Raised when a complete in-memory draft cannot be created."""


@dataclass(frozen=True)
class GenerationConfig:
    """User-controlled settings for one draft generation run."""

    instruction: str = ""
    temperature: float = 0.7
    max_output_tokens: int = 4096
    rows_per_table: int = 10

    def __post_init__(self) -> None:
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if not 1 <= self.rows_per_table <= 100:
            raise ValueError("rows_per_table must be between 1 and 100")


@dataclass(frozen=True)
class GenerationProgress:
    """A user-facing state transition emitted during draft generation."""

    kind: Literal["started", "table_started", "table_complete", "deferred_started", "deferred_complete", "complete"]
    message: str
    table: str | None = None
    completed_steps: int = 0
    total_steps: int = 0


@dataclass(frozen=True)
class SemanticGenerationRequest:
    """A batch of non-structural values requested from a semantic generator."""

    table: Table
    columns: tuple[Column, ...]
    row_count: int
    instruction: str
    temperature: float
    max_output_tokens: int


class SemanticValueGenerator(Protocol):
    """Gateway for structured semantic values; implemented by infrastructure."""

    def generate(
        self,
        request: SemanticGenerationRequest,
        *,
        on_text: Callable[[str], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Return exactly the requested rows, using only requested columns."""


class LocalSemanticValueGenerator:
    """Provide deterministic placeholder text without contacting an LLM.

    This adapter keeps local demos usable when Vertex AI is intentionally not
    configured. Structural values are still produced and validated by this
    module; the adapter only fills the text fields that would otherwise be
    requested from Gemini.
    """

    def generate(
        self,
        request: SemanticGenerationRequest,
        *,
        on_text: Callable[[str], None] | None = None,
    ) -> list[dict[str, Any]]:
        if on_text is not None:
            on_text("Generated deterministic local text values.")
        return [
            {
                column.name: f"{request.table.name} {column.name} {row_index}"
                for column in request.columns
            }
            for row_index in range(1, request.row_count + 1)
        ]


@dataclass(frozen=True)
class DraftDataset:
    """A generated, session-only dataset suitable for preview."""

    rows_by_table: Mapping[str, tuple[dict[str, Any], ...]]
    plan: DependencyPlan
    config: GenerationConfig

    def rows_for(self, table_name: str) -> tuple[dict[str, Any], ...]:
        return self.rows_by_table[table_name]


ProgressCallback = Callable[[GenerationProgress], None]

_SEMANTIC_BATCH_SIZE = 10


def generate_draft(
    schema: Schema,
    config: GenerationConfig,
    semantic_generator: SemanticValueGenerator,
    *,
    on_progress: ProgressCallback | None = None,
) -> DraftDataset:
    """Generate a session-only draft in the deterministic dependency order.

    Primary keys, foreign keys, enum values and basic type shapes are made
    locally.  Gemini (or another injected gateway) only supplies optional
    semantic strings such as names, descriptions and addresses.
    """

    plan = plan_generation(schema)
    if not plan.is_supported:
        statuses = "; ".join(cycle.status for cycle in plan.cycles if not cycle.supported)
        raise DraftGenerationError(f"Draft generation is blocked: {statuses}")

    rows_by_table: dict[str, list[dict[str, Any]]] = {table.name: [] for table in schema.tables}
    tables_by_name = {table.name: table for table in schema.tables}
    deferred_columns = _deferred_columns(plan)
    create_tables = [table_name for phase in plan.phases if phase.kind == "create" for table_name in phase.tables]
    total_steps = len(create_tables) + sum(1 for phase in plan.phases if phase.kind == "deferred_update")
    completed_steps = 0
    _emit(on_progress, "started", "Preparing draft generation.", total_steps=total_steps)

    for phase in plan.phases:
        if phase.kind == "create":
            for table_name in phase.tables:
                table = tables_by_name[table_name]
                _emit(
                    on_progress,
                    "table_started",
                    f"Generating {table.name}.",
                    table=table.name,
                    completed_steps=completed_steps,
                    total_steps=total_steps,
                )
                rows_by_table[table.name] = _create_table_rows(
                    table,
                    config,
                    rows_by_table,
                    deferred_columns,
                    semantic_generator,
                    on_progress,
                )
                completed_steps += 1
                _emit(
                    on_progress,
                    "table_complete",
                    f"Generated {len(rows_by_table[table.name])} rows for {table.name}.",
                    table=table.name,
                    completed_steps=completed_steps,
                    total_steps=total_steps,
                )
        else:
            _emit(
                on_progress,
                "deferred_started",
                "Populating deferred foreign-key relationships.",
                completed_steps=completed_steps,
                total_steps=total_steps,
            )
            for relationship in phase.relationships:
                _populate_deferred_relationship(relationship, rows_by_table)
            completed_steps += 1
            _emit(
                on_progress,
                "deferred_complete",
                "Deferred foreign-key relationships are populated.",
                completed_steps=completed_steps,
                total_steps=total_steps,
            )

    _emit(on_progress, "complete", "Draft generation complete.", completed_steps=completed_steps, total_steps=total_steps)
    return DraftDataset(
        rows_by_table={name: tuple(rows) for name, rows in rows_by_table.items()},
        plan=plan,
        config=config,
    )


def _create_table_rows(
    table: Table,
    config: GenerationConfig,
    rows_by_table: Mapping[str, list[dict[str, Any]]],
    deferred_columns: set[tuple[str, str]],
    semantic_generator: SemanticValueGenerator,
    on_progress: ProgressCallback | None,
) -> list[dict[str, Any]]:
    rows = [
        {
            column.name: _base_value(table, column, row_index)
            for column in table.columns
        }
        for row_index in range(1, config.rows_per_table + 1)
    ]
    foreign_key_columns = {column for foreign_key in table.foreign_keys for column in foreign_key.columns}
    for row_index, row in enumerate(rows):
        for foreign_key in table.foreign_keys:
            if any((table.name, column) in deferred_columns for column in foreign_key.columns):
                for column in foreign_key.columns:
                    row[column] = None
            else:
                _assign_foreign_key(row, foreign_key.columns, foreign_key.referenced_table, foreign_key.referenced_columns, row_index, rows_by_table)

    semantic_columns = tuple(
        column
        for column in table.columns
        if _is_semantic(column) and column.name not in foreign_key_columns and column.name not in table.primary_key
    )
    if not semantic_columns:
        return rows

    for start in range(0, len(rows), _SEMANTIC_BATCH_SIZE):
        batch = rows[start : start + _SEMANTIC_BATCH_SIZE]
        request = SemanticGenerationRequest(
            table=table,
            columns=semantic_columns,
            row_count=len(batch),
            instruction=config.instruction,
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
        )
        try:
            semantic_rows = semantic_generator.generate(request, on_text=lambda _: _emit(
                on_progress,
                "table_started",
                f"Receiving structured values for {table.name}.",
                table=table.name,
            ))
        except Exception as error:
            raise DraftGenerationError(f"Could not generate semantic values for {table.name}: {error}") from error
        if len(semantic_rows) != len(batch):
            raise DraftGenerationError(
                f"Semantic generator returned {len(semantic_rows)} rows for {table.name}; expected {len(batch)}."
            )
        for row, semantic_values in zip(batch, semantic_rows, strict=True):
            for column in semantic_columns:
                value = semantic_values.get(column.name)
                if isinstance(value, str) and value.strip():
                    row[column.name] = value.strip()
    return rows


def _assign_foreign_key(
    row: dict[str, Any],
    source_columns: list[str],
    referenced_table: str,
    referenced_columns: list[str],
    row_index: int,
    rows_by_table: Mapping[str, list[dict[str, Any]]],
) -> None:
    referenced_rows = rows_by_table.get(referenced_table)
    if not referenced_rows:
        raise DraftGenerationError(f"Referenced rows for {referenced_table} are unavailable.")
    referenced_row = referenced_rows[row_index % len(referenced_rows)]
    for source_column, referenced_column in zip(source_columns, referenced_columns, strict=True):
        row[source_column] = referenced_row[referenced_column]


def _populate_deferred_relationship(
    relationship: DeferredRelationship,
    rows_by_table: Mapping[str, list[dict[str, Any]]],
) -> None:
    source_rows = rows_by_table[relationship.source_table]
    referenced_rows = rows_by_table[relationship.referenced_table]
    if not referenced_rows:
        raise DraftGenerationError(f"Deferred relationship target {relationship.referenced_table} has no rows.")
    for row_index, row in enumerate(source_rows):
        referenced_row = referenced_rows[row_index % len(referenced_rows)]
        for source_column, referenced_column in zip(
            relationship.source_columns, relationship.referenced_columns, strict=True
        ):
            row[source_column] = referenced_row[referenced_column]


def _deferred_columns(plan: DependencyPlan) -> set[tuple[str, str]]:
    return {
        (relationship.source_table, source_column)
        for phase in plan.phases
        if phase.kind == "deferred_update"
        for relationship in phase.relationships
        for source_column in relationship.source_columns
    }


def _is_semantic(column: Column) -> bool:
    if column.is_unique or column.enum_values:
        return False
    return column.postgres_type.upper().startswith(("TEXT", "VARCHAR", "CHAR"))


def _base_value(table: Table, column: Column, row_index: int) -> Any:
    if column.name in table.primary_key:
        return _identifier_value(table, column, row_index)
    if column.enum_values:
        return column.enum_values[(row_index - 1) % len(column.enum_values)]
    column_type = column.postgres_type.upper()
    if "BOOL" in column_type:
        return row_index % 2 == 1
    if column_type.startswith(("INT", "SMALLINT", "BIGINT", "NUMERIC", "DECIMAL", "REAL", "DOUBLE", "FLOAT")):
        return _number_value(column, row_index)
    if "TIMESTAMP" in column_type or "DATETIME" in column_type:
        return (datetime(2024, 1, 1, 9, 0, 0) + timedelta(days=row_index - 1)).isoformat(sep=" ")
    if column_type == "DATE":
        return (date(2024, 1, 1) + timedelta(days=row_index - 1)).isoformat()
    if column_type == "TIME":
        return f"{8 + (row_index % 8):02d}:00:00"
    if "JSON" in column_type:
        return {"row": row_index}
    return _string_value(table, column, row_index)


def _identifier_value(table: Table, column: Column, row_index: int) -> Any:
    if column.postgres_type.upper().startswith(("INT", "SMALLINT", "BIGINT")):
        return row_index
    return f"{table.name.lower()}-{row_index}"


def _number_value(column: Column, row_index: int) -> int | Decimal:
    lower, upper = _numeric_bounds(column)
    value = lower + ((row_index - 1) % (upper - lower + 1)) if upper is not None else lower + row_index - 1
    if column.postgres_type.upper().startswith(("INT", "SMALLINT", "BIGINT")):
        return int(value)
    return Decimal(value) + Decimal("0.50")


def _numeric_bounds(column: Column) -> tuple[int, int | None]:
    expression = " ".join(check.expression for check in column.checks)
    lower_match = re.search(rf"\b{re.escape(column.name)}\s*>=\s*(-?\d+)", expression, re.IGNORECASE)
    upper_match = re.search(rf"\b{re.escape(column.name)}\s*<=\s*(-?\d+)", expression, re.IGNORECASE)
    return (int(lower_match.group(1)) if lower_match else 1, int(upper_match.group(1)) if upper_match else None)


def _string_value(table: Table, column: Column, row_index: int) -> str:
    name = column.name.lower()
    if "email" in name:
        return f"{table.name.lower()}-{row_index}@example.test"
    if "phone" in name:
        return f"+1-555-010-{row_index:04d}"
    if "zip" in name or "postal" in name:
        return f"{10000 + row_index:05d}"
    if "website" in name:
        return f"https://{table.name.lower()}-{row_index}.example.test"
    if "isbn" in name:
        return f"978-0-000-{row_index:05d}-0"
    if "license" in name:
        return f"LIC-{row_index:06d}"
    return f"{table.name} {column.name} {row_index}"


def _emit(
    callback: ProgressCallback | None,
    kind: Literal["started", "table_started", "table_complete", "deferred_started", "deferred_complete", "complete"],
    message: str,
    *,
    table: str | None = None,
    completed_steps: int = 0,
    total_steps: int = 0,
) -> None:
    if callback is not None:
        callback(GenerationProgress(kind, message, table, completed_steps, total_steps))
