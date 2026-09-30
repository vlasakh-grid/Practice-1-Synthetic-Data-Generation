"""Use-case orchestration for dataset generation and persistence."""

from __future__ import annotations

from collections.abc import Callable

from dataset_repository import DatasetRepository, DatasetRepositoryError, StoredDataset
from domain.draft_generation import (
    DraftDataset,
    GenerationConfig,
    GenerationProgress,
    SemanticValueGenerator,
    generate_draft,
)
from domain.schema import Schema
from domain.validation import ValidationResult, validate_dataset


class DatasetService:
    """Coordinate domain generation with the PostgreSQL repository."""

    def __init__(
        self,
        repository: DatasetRepository | None,
        semantic_generator: SemanticValueGenerator,
    ) -> None:
        self.repository = repository
        self.semantic_generator = semantic_generator

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

    def save(self, schema: Schema, draft: DraftDataset, schema_digest: str) -> StoredDataset:
        if self.repository is None:
            raise DatasetRepositoryError("PostgreSQL is not configured.")
        self.repository.save(schema, draft, schema_digest)
        restored = self.repository.load_current()
        if restored is None:
            raise DatasetRepositoryError("The dataset was saved but could not be restored.")
        return restored
