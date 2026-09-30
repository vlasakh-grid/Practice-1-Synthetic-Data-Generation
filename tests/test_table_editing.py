from datetime import datetime, timezone
import unittest

from application.dataset_service import DatasetService
from dataset_repository import InvalidDatasetError, StoredDataset
from domain.ddl_parser import parse_ddl


class _UnusedSemanticGenerator:
    def generate(self, request, *, on_text=None):
        raise AssertionError("Generation is not part of a table-edit test")


class _EditingGateway:
    def __init__(self, change) -> None:
        self.change = change
        self.requests = []

    def edit(self, request):
        self.requests.append(request)
        return self.change([dict(row) for row in request.rows])


class _RecordingRepository:
    def __init__(self, current) -> None:
        self.current = current
        self.save_calls = 0

    def save(self, schema, draft, schema_digest):
        self.save_calls += 1
        self.current = StoredDataset(schema, draft.rows_by_table, schema_digest, datetime(2026, 9, 30, tzinfo=timezone.utc))

    def load_current(self):
        return self.current


def _current_dataset():
    schema = parse_ddl(
        """
        CREATE TABLE parents (id INT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE children (
            id INT PRIMARY KEY,
            parent_id INT NOT NULL,
            label TEXT NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES parents(id)
        );
        """
    )
    return StoredDataset(
        schema,
        {
            "parents": ({"id": 1, "name": "Original parent"},),
            "children": ({"id": 1, "parent_id": 1, "label": "Original child"},),
        },
        "schema-digest",
        datetime(2026, 9, 30, tzinfo=timezone.utc),
    )


class TableEditingTests(unittest.TestCase):
    def test_selected_table_is_replaced_and_related_tables_are_unchanged(self) -> None:
        current = _current_dataset()
        gateway = _EditingGateway(lambda rows: [{**rows[0], "name": "Revised parent"}])
        service = DatasetService(None, _UnusedSemanticGenerator(), gateway)

        candidate, validation = service.edit_current(current, "parents", "Make the parent more descriptive.")

        self.assertTrue(validation.is_valid)
        self.assertEqual(candidate.rows_for("parents"), ({"id": 1, "name": "Revised parent"},))
        self.assertEqual(candidate.rows_for("children"), current.rows_for("children"))
        self.assertEqual(gateway.requests[0].instruction, "Make the parent more descriptive.")

    def test_invalid_candidate_never_reaches_the_repository(self) -> None:
        current = _current_dataset()
        repository = _RecordingRepository(current)
        gateway = _EditingGateway(lambda rows: [{**rows[0], "name": None}])
        service = DatasetService(repository, _UnusedSemanticGenerator(), gateway)

        with self.assertRaises(InvalidDatasetError) as raised:
            service.apply_edit(current, "parents", "Remove the name.")

        self.assertFalse(raised.exception.result.is_valid)
        self.assertEqual(repository.save_calls, 0)
        self.assertEqual(repository.current.rows_for("parents"), current.rows_for("parents"))

    def test_primary_and_foreign_keys_cannot_be_changed(self) -> None:
        current = _current_dataset()
        gateway = _EditingGateway(lambda rows: [{**rows[0], "parent_id": 99}])
        service = DatasetService(None, _UnusedSemanticGenerator(), gateway)

        with self.assertRaisesRegex(RuntimeError, "protected field 'parent_id'"):
            service.edit_current(current, "children", "Move the child to a different parent.")


if __name__ == "__main__":
    unittest.main()
