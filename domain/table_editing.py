"""Safe, table-scoped editing of an existing synthetic dataset."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from .draft_generation import DraftDataset
from .schema import Table


class TableEditError(RuntimeError):
    """Raised when a structured table edit cannot be safely applied."""


@dataclass(frozen=True)
class TableEditRequest:
    """The selected table and the exact rows Gemini may revise."""

    table: Table
    rows: tuple[dict[str, Any], ...]
    instruction: str
    temperature: float = 0.7
    max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        if not self.instruction.strip():
            raise ValueError("An edit instruction is required.")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")


class TableEditor(Protocol):
    """Port for an LLM that returns a complete replacement of one table's rows."""

    def edit(self, request: TableEditRequest) -> list[dict[str, Any]]:
        """Return rows matching ``request.rows`` in count, fields, and order."""


def apply_table_edit(
    draft: DraftDataset,
    table: Table,
    instruction: str,
    editor: TableEditor,
    *,
    temperature: float = 0.7,
    max_output_tokens: int = 4096,
) -> DraftDataset:
    """Replace one table after enforcing its structural invariants.

    Primary and foreign-key values remain local to the existing dataset. This
    lets Gemini revise human-readable values without changing row identity or
    relationship membership.
    """

    source_rows = tuple(dict(row) for row in draft.rows_for(table.name))
    request = TableEditRequest(
        table=table,
        rows=source_rows,
        instruction=instruction,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    try:
        edited_rows = editor.edit(request)
    except TableEditError:
        raise
    except Exception as error:
        raise TableEditError(f"Could not edit {table.name}: {error}") from error

    _validate_edited_rows(table, source_rows, edited_rows)
    rows_by_table = dict(draft.rows_by_table)
    rows_by_table[table.name] = tuple(dict(row) for row in edited_rows)
    return replace(draft, rows_by_table=rows_by_table)


def _validate_edited_rows(
    table: Table,
    source_rows: tuple[dict[str, Any], ...],
    edited_rows: list[dict[str, Any]],
) -> None:
    if not isinstance(edited_rows, list):
        raise TableEditError(f"The editor response for {table.name} must contain a rows array.")
    if len(edited_rows) != len(source_rows):
        raise TableEditError(
            f"The editor returned {len(edited_rows)} rows for {table.name}; expected {len(source_rows)}."
        )

    expected_fields = {column.name for column in table.columns}
    protected_fields = set(table.primary_key)
    protected_fields.update(column for foreign_key in table.foreign_keys for column in foreign_key.columns)
    for row_number, (source_row, edited_row) in enumerate(zip(source_rows, edited_rows, strict=True), start=1):
        if not isinstance(edited_row, Mapping):
            raise TableEditError(f"Row {row_number} returned for {table.name} is not an object.")
        fields = set(edited_row)
        if fields != expected_fields:
            missing = ", ".join(sorted(expected_fields - fields))
            unexpected = ", ".join(sorted(fields - expected_fields))
            details = ", ".join(part for part in (
                f"missing fields: {missing}" if missing else "",
                f"unexpected fields: {unexpected}" if unexpected else "",
            ) if part)
            raise TableEditError(f"Row {row_number} returned for {table.name} has the wrong fields ({details}).")
        for field in protected_fields:
            if edited_row[field] != source_row[field]:
                raise TableEditError(
                    f"The editor changed protected field {field!r} in {table.name} row {row_number}."
                )
