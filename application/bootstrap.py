"""Build the application runtime without rendering Streamlit components."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from application.dataset_service import DatasetService
from application.runtime import AppRuntime
from dataset_repository import DatasetRepository, DatasetRepositoryError
from llm import GeminiSemanticValueGenerator


def _repository_from_environment() -> DatasetRepository | None:
    database_url = os.getenv("DATABASE_URL")
    return DatasetRepository.from_url(database_url) if database_url else None


def build_runtime() -> AppRuntime:
    """Create infrastructure gateways and restore the current dataset."""

    load_dotenv()
    repository = _repository_from_environment()
    service = DatasetService(repository, GeminiSemanticValueGenerator())
    if repository is None:
        return AppRuntime(repository=repository, dataset_service=service)

    try:
        persisted_dataset = service.restore_current()
    except DatasetRepositoryError as error:
        return AppRuntime(
            repository=repository,
            dataset_service=service,
            restore_error=str(error),
        )
    return AppRuntime(
        repository=repository,
        dataset_service=service,
        persisted_dataset=persisted_dataset,
    )
