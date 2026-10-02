"""Runtime dependencies assembled for one Streamlit application run."""

from __future__ import annotations

from dataclasses import dataclass

from application.data_chat_service import DataChatService
from application.dataset_service import DatasetService
from dataset_repository import DatasetRepository, StoredDataset


@dataclass
class AppRuntime:
    """Application services and the current persisted dataset for the UI."""

    repository: DatasetRepository | None
    dataset_service: DatasetService
    persisted_dataset: StoredDataset | None = None
    restore_error: str | None = None
    chat_service: DataChatService | None = None
    generation_mode: str = "Gemini (Vertex AI)"
