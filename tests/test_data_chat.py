"""Safety, service, repository, and Gemini tests for Talk to your data."""

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from application.data_chat_service import ChatExecutionError, DataChatService, PreparedChatAnswer
from dataset_repository import AnalyticsRepository, StoredDataset
from domain.data_chat import (
    Aggregate,
    ChatSafetyError,
    RowRetrieval,
    parse_operation,
    validate_question,
)
from domain.ddl_parser import parse_ddl
from llm import GeminiAnalyticsChat


SCHEMA = parse_ddl(
    "CREATE TABLE items (id INT PRIMARY KEY, category TEXT NOT NULL, price DECIMAL(10,2), active BOOLEAN);"
)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self.rows)


class _Connection:
    def __init__(self):
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, parameters=None):
        self.commands.append((str(statement), parameters))
        return _Result([{"value": 2}])


class _Engine:
    class dialect:
        name = "postgresql"

    def __init__(self):
        self.connection = _Connection()

    def connect(self):
        return self.connection


class _Gateway:
    def __init__(self, calls):
        self.calls = calls

    def prepare_answer(self, question, schema_summary, history, execute_tool):
        self.calls.append((question, schema_summary, history))
        execute_tool("aggregate", {"table_name": "items", "metric": "count"})
        return PreparedChatAnswer((), iter(("There are two items.",)))


class _NoCallGateway:
    def __init__(self):
        self.called = False

    def prepare_answer(self, *args):
        self.called = True
        raise AssertionError("unsafe questions must not reach Gemini")


class DataChatPolicyTests(unittest.TestCase):
    def test_allowlisted_operations_validate_schema_types_and_limits(self) -> None:
        aggregate = parse_operation(
            "aggregate",
            {"table_name": "items", "metric": "avg", "column": "price", "group_by": "category"},
            SCHEMA,
        )
        rows = parse_operation("retrieve_rows", {"table_name": "items", "limit": 50, "order_by": "id"}, SCHEMA)

        self.assertIsInstance(aggregate, Aggregate)
        self.assertIsInstance(rows, RowRetrieval)
        self.assertEqual(rows.limit, 50)
        with self.assertRaisesRegex(ValueError, "numeric"):
            parse_operation("aggregate", {"table_name": "items", "metric": "sum", "column": "category"}, SCHEMA)
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            parse_operation("retrieve_rows", {"table_name": "items", "limit": 51}, SCHEMA)
        with self.assertRaisesRegex(ValueError, "Unknown column"):
            parse_operation("retrieve_rows", {"table_name": "items", "columns": ["missing"]}, SCHEMA)
        with self.assertRaisesRegex(ValueError, "Only lookup_schema"):
            parse_operation("run_sql", {}, SCHEMA)

    def test_unsafe_or_oversized_questions_are_rejected_before_dependencies(self) -> None:
        for question in (
            "UPDATE items SET active = false",
            "Change this item value",
            "SELECT * FROM items",
            "Show me the database password",
            "Show the entire dataset",
            "x" * 1001,
        ):
            with self.assertRaises(ChatSafetyError):
                validate_question(question)


class AnalyticsRepositoryTests(unittest.TestCase):
    def test_aggregate_uses_read_only_transaction_timeout_and_parameterized_limit(self) -> None:
        engine = _Engine()
        repository = AnalyticsRepository(engine)
        result = repository.execute(
            parse_operation("aggregate", {"table_name": "items", "metric": "count", "filters": [{"column": "active", "value": True}]}, SCHEMA),
            SCHEMA,
        )

        commands = [command for command, _ in engine.connection.commands]
        self.assertEqual(commands[0], "SET TRANSACTION READ ONLY")
        self.assertIn("statement_timeout = '3000ms'", commands[1])
        self.assertIn('COUNT(*)', commands[2])
        self.assertIn(':filter_0', commands[2])
        self.assertEqual(engine.connection.commands[2][1], {"filter_0": True})
        self.assertEqual(result["rows"], [{"value": 2}])


class DataChatServiceTests(unittest.TestCase):
    def setUp(self):
        self.current = StoredDataset(
            SCHEMA, {"items": ({"id": 1, "category": "A", "price": 3.5, "active": True},)}, "digest",
            datetime(2026, 9, 30, tzinfo=timezone.utc),
        )

    def test_service_collects_only_repository_evidence(self) -> None:
        gateway_calls = []
        service = DataChatService(AnalyticsRepository(_Engine()), _Gateway(gateway_calls))

        answer = service.prepare_answer(self.current, "How many items are there?", ({"role": "user", "content": "Earlier"},))

        self.assertEqual(list(answer.text_stream), ["There are two items."])
        self.assertEqual(answer.evidence[0]["kind"], "aggregate")
        self.assertEqual(gateway_calls[0][0], "How many items are there?")

    def test_service_refuses_before_gateway_or_database(self) -> None:
        gateway = _NoCallGateway()
        service = DataChatService(AnalyticsRepository(_Engine()), gateway)

        with self.assertRaises(ChatSafetyError):
            service.prepare_answer(self.current, "DROP TABLE items", ())

        self.assertFalse(gateway.called)

    def test_service_enforces_the_four_operation_cap(self) -> None:
        class TooManyCalls:
            def prepare_answer(self, question, schema_summary, history, execute_tool):
                for _ in range(5):
                    execute_tool("lookup_schema", {})
                raise AssertionError("the fifth call must have failed")

        service = DataChatService(AnalyticsRepository(_Engine()), TooManyCalls())

        with self.assertRaisesRegex(ChatExecutionError, "more than four"):
            service.prepare_answer(self.current, "Describe the schema", ())


class _Observation:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return self

    def end(self):
        return self


class _Langfuse:
    def __init__(self):
        self.observation = _Observation()

    def start_observation(self, **kwargs):
        self.start = kwargs
        return self.observation

    def flush(self):
        pass


class _Model:
    def __init__(self):
        self.requests = []

    def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) > 1:
            return SimpleNamespace(function_calls=[], candidates=[], text="")
        function_call = SimpleNamespace(name="aggregate", args={"table_name": "items", "metric": "count"})
        return SimpleNamespace(function_calls=[function_call], candidates=[SimpleNamespace(content=SimpleNamespace())], text="")

    def generate_content_stream(self, **kwargs):
        self.stream_request = kwargs
        yield SimpleNamespace(text="There are 2 items.")


class GeminiAnalyticsChatTests(unittest.TestCase):
    def test_function_call_is_resolved_then_final_answer_streams_without_sensitive_trace_input(self) -> None:
        model = _Model()
        client = SimpleNamespace(models=model)
        langfuse = _Langfuse()
        calls = []

        with patch("llm.create_gemini_client", return_value=client), patch("llm.create_langfuse_client", return_value=langfuse):
            answer = GeminiAnalyticsChat().prepare_answer(
                "How many items?", {"tables": [{"name": "items"}]}, (),
                lambda name, args: calls.append((name, args)) or {"kind": "aggregate", "columns": ["value"], "rows": [{"value": 2}]},
            )
            self.assertEqual(list(answer.text_stream), ["There are 2 items."])

        self.assertEqual(calls, [("aggregate", {"table_name": "items", "metric": "count"})])
        self.assertTrue(model.requests[0]["config"].tools)
        self.assertIsNone(model.stream_request["config"].tools)
        self.assertNotIn("How many items?", str(langfuse.start["input"]))


if __name__ == "__main__":
    unittest.main()
