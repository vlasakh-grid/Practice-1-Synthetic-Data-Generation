"""Build the application runtime without rendering Streamlit components."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from application.data_chat_service import DataChatService
from application.dataset_service import DatasetService
from application.runtime import AppRuntime
from dataset_repository import AnalyticsRepository, DatasetRepository, DatasetRepositoryError
from llm import GeminiAnalyticsChat, GeminiSemanticValueGenerator, GeminiTableEditor


def _repository_from_environment() -> DatasetRepository | None:
    database_url = os.getenv("DATABASE_URL")
    reader_role = os.getenv("ANALYTICS_DB_USER", "").strip() or None
    return DatasetRepository.from_url(database_url, reader_role=reader_role) if database_url else None


def _chat_service_from_environment() -> DataChatService:
    """Build the chat path separately so it cannot inherit writer credentials."""

    analytics_url = os.getenv("ANALYTICS_DATABASE_URL", "").strip()
    repository = AnalyticsRepository.from_url(analytics_url) if analytics_url else None
    return DataChatService(repository, GeminiAnalyticsChat())


def build_runtime() -> AppRuntime:
    """Create infrastructure gateways and restore the current dataset."""

    load_dotenv()
    repository = _repository_from_environment()
    service = DatasetService(repository, GeminiSemanticValueGenerator(), GeminiTableEditor())
    chat_service = _chat_service_from_environment()
    if repository is None:
        return AppRuntime(repository=repository, dataset_service=service, chat_service=chat_service)

    try:
        persisted_dataset = service.restore_current()
    except DatasetRepositoryError as error:
        return AppRuntime(
            repository=repository,
            dataset_service=service,
            chat_service=chat_service,
            restore_error=str(error),
        )
    return AppRuntime(
        repository=repository,
        dataset_service=service,
        chat_service=chat_service,
        persisted_dataset=persisted_dataset,
    )
