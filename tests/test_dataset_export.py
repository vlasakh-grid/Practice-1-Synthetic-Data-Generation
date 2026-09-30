"""Regression coverage for persisted-dataset downloads."""

import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
import unittest
from zipfile import ZipFile

from application.dataset_export import export_dataset_zip, export_table_csv
from dataset_repository import StoredDataset
from domain.ddl_parser import parse_ddl


def _dataset() -> StoredDataset:
    schema = parse_ddl(
        """
        CREATE TABLE parents (parent_id INT PRIMARY KEY, name TEXT, note TEXT);
        CREATE TABLE children (child_id INT PRIMARY KEY, parent_id INT, description TEXT);
        """
    )
    return StoredDataset(
        schema,
        {
            "parents": (
                {"note": "comma, quote \" and newline\n", "name": "Ada", "parent_id": 1},
                {"parent_id": 2, "name": None, "note": None},
            ),
            "children": ({"description": "first child", "parent_id": 1, "child_id": 10},),
        },
        "digest",
        datetime(2026, 9, 30, tzinfo=timezone.utc),
    )


class DatasetExportTests(unittest.TestCase):
    def test_table_csv_uses_schema_column_order_and_blank_cells_for_null(self) -> None:
        exported = export_table_csv(_dataset(), "parents")

        self.assertEqual(
            list(csv.reader(StringIO(exported.decode("utf-8")))),
            [
                ["parent_id", "name", "note"],
                ["1", "Ada", "comma, quote \" and newline\n"],
                ["2", "", ""],
            ],
        )

    def test_dataset_zip_has_one_csv_per_schema_table_in_schema_order(self) -> None:
        exported = export_dataset_zip(_dataset())

        with ZipFile(BytesIO(exported)) as archive:
            self.assertEqual(archive.namelist(), ["parents.csv", "children.csv"])
            self.assertEqual(
                list(csv.reader(StringIO(archive.read("children.csv").decode("utf-8")))),
                [["child_id", "parent_id", "description"], ["10", "1", "first child"]],
            )

    def test_unknown_table_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown table selected for export"):
            export_table_csv(_dataset(), "missing")


if __name__ == "__main__":
    unittest.main()
