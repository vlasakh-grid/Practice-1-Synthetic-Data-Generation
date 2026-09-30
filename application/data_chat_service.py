"""Application boundary for session-scoped, read-only data conversations."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from dataset_repository import AnalyticsRepository, AnalyticsRepositoryError, StoredDataset
from domain.data_chat import AnalyticsOperationError, MAX_TOOL_CALLS, parse_operation, validate_question


class ChatUnavailableError(RuntimeError):
    """Raised when chat dependencies are not configured for this application run."""


class ChatExecutionError(RuntimeError):
    """A safe, user-facing wrapper around a failed model or analytics operation."""


@dataclass(frozen=True)
class PreparedChatAnswer:
    """Evidence already collected for an answer and its final streamed text."""

    evidence: tuple[dict[str, Any], ...]
    text_stream: Iterable[str]


class AnalyticsChatGateway(Protocol):
    """The Gemini adapter interface, deliberately independent of Streamlit."""

    def prepare_answer(
        self,
        question: str,
        schema_summary: dict[str, Any],
        history: tuple[Mapping[str, str], ...],
        execute_tool: Callable[[str, Mapping[str, Any]], dict[str, Any]],
    ) -> PreparedChatAnswer: ...


class DataChatService:
    """Validate chat input and mediate all model-requested data access."""

    def __init__(self, repository: AnalyticsRepository | None, gateway: AnalyticsChatGateway | None) -> None:
        self.repository = repository
        self.gateway = gateway

    def prepare_answer(
        self,
        current: StoredDataset,
        question: str,
        history: tuple[Mapping[str, str], ...],
    ) -> PreparedChatAnswer:
        safe_question = validate_question(question)
        if self.repository is None:
            raise ChatUnavailableError("Read-only PostgreSQL analytics is not configured. Check the demo setup guide.")
        if self.gateway is None:
            raise ChatUnavailableError("Gemini chat is not configured. Check the Vertex AI and Langfuse settings.")
        calls = 0
        evidence: list[dict[str, Any]] = []

        def execute_tool(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if calls > MAX_TOOL_CALLS:
                raise ChatExecutionError("This question needs more than four data operations. Please make it more specific.")
            try:
                operation = parse_operation(name, arguments, current.schema)
                result = self.repository.execute(operation, current.schema)
            except (AnalyticsOperationError, AnalyticsRepositoryError) as error:
                raise ChatExecutionError(str(error)) from error
            evidence.append(result)
            return result

        try:
            answer = self.gateway.prepare_answer(
                safe_question,
                _model_schema_summary(current),
                history,
                execute_tool,
            )
        except (ChatExecutionError, ChatUnavailableError):
            raise
        except Exception as error:
            raise ChatExecutionError("The assistant could not complete that analysis. Please try a simpler question.") from error
        # The gateway returns the exact evidence it used; retain service-collected
        # evidence as the authority so a gateway cannot fabricate UI tables.
        return PreparedChatAnswer(tuple(evidence), answer.text_stream)


def _model_schema_summary(current: StoredDataset) -> dict[str, Any]:
    """Expose names/types only; model context never contains credentials or connection details."""

    return {
        "dataset_saved_at": current.saved_at.isoformat(),
        "tables": [
            {
                "name": table.name,
                "columns": [{"name": column.name, "type": column.postgres_type} for column in table.columns],
            }
            for table in current.schema.tables
        ],
    }
