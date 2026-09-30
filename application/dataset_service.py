"""Use-case orchestration for dataset generation and persistence."""

from __future__ import annotations

from collections.abc import Callable

from dataset_repository import DatasetRepository, DatasetRepositoryError, InvalidDatasetError, StoredDataset
from domain.dependency_planner import plan_generation
from domain.draft_generation import (
    DraftDataset,
    GenerationConfig,
    GenerationProgress,
    SemanticValueGenerator,
    generate_draft,
)
from domain.schema import Schema
from domain.table_editing import TableEditor, apply_table_edit
from domain.validation import ValidationResult, validate_dataset


class DatasetService:
    """Coordinate domain generation with the PostgreSQL repository."""

    def __init__(
        self,
        repository: DatasetRepository | None,
        semantic_generator: SemanticValueGenerator,
        table_editor: TableEditor | None = None,
    ) -> None:
        self.repository = repository
        self.semantic_generator = semantic_generator
        self.table_editor = table_editor

    def generate(
        self,
        schema: Schema,
        config: GenerationConfig,
        *,
        on_progress: Callable[[GenerationProgress], None] | None = None,
    ) -> DraftDataset:
        return generate_draft(
            schema,
            config,
            self.semantic_generator,
            on_progress=on_progress,
        )

    def restore_current(self) -> StoredDataset | None:
        if self.repository is None:
            return None
        return self.repository.load_current()

    def validate(self, schema: Schema, draft: DraftDataset) -> ValidationResult:
        return validate_dataset(schema, draft)

    def edit_current(
        self,
        current: StoredDataset,
        table_name: str,
        instruction: str,
        *,
        temperature: float = 0.7,
        max_output_tokens: int = 4096,
    ) -> tuple[DraftDataset, ValidationResult]:
        """Apply a structured edit and validate the complete candidate dataset."""

        if self.table_editor is None:
            raise DatasetRepositoryError("Gemini table editing is not configured.")
        try:
            table = current.schema.table(table_name)
        except KeyError as error:
            raise ValueError(f"Unknown table selected for editing: {table_name}") from error
        source_rows = {name: tuple(dict(row) for row in rows) for name, rows in current.rows_by_table.items()}
        draft = DraftDataset(
            rows_by_table=source_rows,
            plan=plan_generation(current.schema),
            config=GenerationConfig(
                instruction=instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                rows_per_table=max(1, len(current.rows_for(table_name))),
            ),
        )
        candidate = apply_table_edit(
            draft,
            table,
            instruction,
            self.table_editor,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        return candidate, self.validate(current.schema, candidate)

    def apply_edit(
        self,
        current: StoredDataset,
        table_name: str,
        instruction: str,
        *,
        temperature: float = 0.7,
        max_output_tokens: int = 4096,
    ) -> StoredDataset:
        """Persist a valid table edit, leaving the current database state untouched otherwise."""

        candidate, validation = self.edit_current(
            current,
            table_name,
            instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        if not validation.is_valid:
            raise InvalidDatasetError(validation)
        return self.save(current.schema, candidate, current.schema_digest)

    def save(self, schema: Schema, draft: DraftDataset, schema_digest: str) -> StoredDataset:
        if self.repository is None:
            raise DatasetRepositoryError("PostgreSQL is not configured.")
        self.repository.save(schema, draft, schema_digest)
        restored = self.repository.load_current()
        if restored is None:
            raise DatasetRepositoryError("The dataset was saved but could not be restored.")
        return restored
