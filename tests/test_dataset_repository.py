from dataclasses import asdict
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

from dataset_repository import DatasetRepository, InvalidDatasetError, _create_table_sql, schema_from_dict
from domain.ddl_parser import parse_ddl
from domain.dependency_planner import plan_generation
from domain.draft_generation import DraftDataset, GenerationConfig


class _NoWriteEngine:
    """Fails a test if an invalid draft reaches the transaction boundary."""

    def begin(self):
        raise AssertionError("An invalid dataset must not begin a database transaction")


class _Result:
    def __init__(self, *, scalar=None, mapping=None, rows=()):
        self.scalar = scalar
        self.mapping = mapping
        self.rows = rows

    def scalar_one(self):
        return self.scalar

    def mappings(self):
        return self

    def first(self):
        return self.mapping

    def __iter__(self):
        return iter(self.rows)


class _Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exception_type, exception, traceback):
        self.connection.rolled_back = exception_type is not None
        return False


class _RecordingConnection:
    saved_at = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

    def __init__(self):
        self.commands = []
        self.metadata = None
        self.rows = []
        self.rolled_back = False

    def execute(self, statement, params=None):
        command = str(statement)
        self.commands.append(command)
        if "SELECT CURRENT_TIMESTAMP" in command:
            return _Result(scalar=self.saved_at)
        if "INSERT INTO \"synthetic_app\".\"current_dataset\"" in command:
            self.metadata = {
                "schema_json": __import__("json").loads(params["schema_json"]),
                "schema_digest": params["schema_digest"],
                "saved_at": params["saved_at"],
            }
        elif "SELECT schema_json" in command:
            return _Result(mapping=self.metadata)
        elif command.startswith('SELECT * FROM "generated_data"'):
            return _Result(rows=self.rows)
        elif command.startswith('INSERT INTO "generated_data"'):
            self.rows.extend(params)
        return _Result()


class _RecordingEngine:
    class dialect:
        name = "postgresql"

    def __init__(self):
        self.connection = _RecordingConnection()

    def begin(self):
        return _Transaction(self.connection)


def _draft(schema, rows_by_table):
    return DraftDataset(
        rows_by_table={name: tuple(rows) for name, rows in rows_by_table.items()},
        plan=plan_generation(schema),
        config=GenerationConfig(rows_per_table=1),
    )


class DatasetRepositoryTests(unittest.TestCase):
    def test_invalid_dataset_never_reaches_the_database(self) -> None:
        schema = parse_ddl("CREATE TABLE items (id INT PRIMARY KEY, name TEXT NOT NULL);")
        draft = _draft(schema, {"items": [{"id": 1, "name": None}]})

        with self.assertRaises(InvalidDatasetError) as raised:
            DatasetRepository(_NoWriteEngine()).save(schema, draft, "digest")

        self.assertFalse(raised.exception.result.is_valid)
        self.assertEqual(raised.exception.result.errors[0].rule, "required")

    def test_stored_schema_round_trips_and_sql_recreates_constraints(self) -> None:
        path = Path(__file__).parents[1] / "task" / "restrurants_schema.ddl"
        schema = parse_ddl(path.read_text())

        restored = schema_from_dict(asdict(schema))
        reviews = restored.table("Reviews")
        sql = _create_table_sql("generated_data", reviews)

        self.assertEqual(restored.as_dict(), schema.as_dict())
        self.assertIn('CREATE TABLE "generated_data"."Reviews"', sql)
        self.assertIn('"rating" >= 1', sql)
        self.assertIn('PRIMARY KEY ("review_id")', sql)

        enum_sql = _create_table_sql("generated_data", restored.table("Orders"))
        self.assertIn('CHECK ("payment_method" IN (\'Credit Card\'', enum_sql)

    @unittest.skipUnless(importlib.util.find_spec("sqlalchemy"), "requires SQLAlchemy")
    def test_save_replaces_data_in_one_transaction_and_load_restores_it(self) -> None:
        schema = parse_ddl("CREATE TABLE items (id INT PRIMARY KEY, name TEXT NOT NULL);")
        draft = _draft(schema, {"items": [{"id": 1, "name": "first"}]})
        engine = _RecordingEngine()
        repository = DatasetRepository(engine)

        saved_at = repository.save(schema, draft, "digest-1")
        restored = repository.load_current()

        self.assertEqual(saved_at, _RecordingConnection.saved_at)
        self.assertFalse(engine.connection.rolled_back)
        self.assertTrue(any(command.startswith('DROP SCHEMA IF EXISTS "generated_data"') for command in engine.connection.commands))
        self.assertEqual(restored.schema.as_dict(), schema.as_dict())
        self.assertEqual(restored.rows_for("items"), ({"id": 1, "name": "first"},))
        self.assertEqual(restored.schema_digest, "digest-1")

    @unittest.skipUnless(importlib.util.find_spec("sqlalchemy"), "requires SQLAlchemy")
    def test_save_grants_reader_only_current_generated_schema_access(self) -> None:
        schema = parse_ddl("CREATE TABLE items (id INT PRIMARY KEY, name TEXT NOT NULL);")
        engine = _RecordingEngine()

        DatasetRepository(engine, reader_role="synthetic_reader").save(schema, _draft(schema, {"items": [{"id": 1, "name": "first"}]}), "digest")

        self.assertIn('GRANT USAGE ON SCHEMA "generated_data" TO "synthetic_reader"', engine.connection.commands)
        self.assertIn('GRANT SELECT ON ALL TABLES IN SCHEMA "generated_data" TO "synthetic_reader"', engine.connection.commands)


if __name__ == "__main__":
    unittest.main()
