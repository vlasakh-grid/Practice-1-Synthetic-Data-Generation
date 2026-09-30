from pathlib import Path
import unittest

from domain.ddl_parser import parse_ddl
from domain.dependency_planner import plan_generation
from domain.draft_generation import DraftDataset, GenerationConfig, generate_draft
from domain.validation import compile_postgres_check, validate_dataset


TASK_DIR = Path(__file__).parents[1] / "task"


class FakeSemanticGenerator:
    def generate(self, request, *, on_text=None):
        return [{column.name: f"{column.name}-{index}" for column in request.columns} for index in range(request.row_count)]


def _draft(schema, rows_by_table):
    return DraftDataset(
        rows_by_table={name: tuple(rows) for name, rows in rows_by_table.items()},
        plan=plan_generation(schema),
        config=GenerationConfig(rows_per_table=2),
    )


class DatasetValidationTests(unittest.TestCase):
    def test_generated_drafts_for_all_supplied_schemas_are_valid(self) -> None:
        for path in sorted(TASK_DIR.glob("*.ddl")):
            with self.subTest(schema=path.name):
                schema = parse_ddl(path.read_text())
                draft = generate_draft(schema, GenerationConfig(rows_per_table=2), FakeSemanticGenerator())
                self.assertTrue(validate_dataset(schema, draft).is_valid)

    def test_reports_each_explicit_constraint_with_location(self) -> None:
        schema = parse_ddl(
            """
            CREATE TABLE parents (id INT PRIMARY KEY);
            CREATE TABLE children (
                id INT PRIMARY KEY,
                required_name VARCHAR(20) NOT NULL,
                status ENUM('new', 'done'),
                external_code VARCHAR(20) UNIQUE,
                parent_id INT,
                score INT CHECK (score >= 1 AND score <= 5),
                group_code VARCHAR(20),
                CONSTRAINT children_pair UNIQUE (status, group_code),
                CONSTRAINT children_group CHECK (group_code IN ('a', 'b')),
                FOREIGN KEY (parent_id) REFERENCES parents(id)
            );
            """
        )
        draft = _draft(
            schema,
            {
                "parents": [{"id": 1}],
                "children": [
                    {"id": 1, "required_name": None, "status": "bad", "external_code": "same", "parent_id": 9, "score": 9, "group_code": "x"},
                    {"id": 1, "required_name": "ok", "status": "bad", "external_code": "same", "parent_id": None, "score": 2, "group_code": "x"},
                ],
            },
        )

        result = validate_dataset(schema, draft)
        self.assertFalse(result.is_valid)
        self.assertTrue({"primary_key", "required", "enum", "unique", "foreign_key", "check"}.issubset({error.rule for error in result.errors}))
        self.assertTrue(all(error.table and error.row >= 1 and error.message for error in result.errors))
        self.assertTrue(any(error.field == "parent_id" and error.rule == "foreign_key" for error in result.errors))
        self.assertTrue(any(error.field is None and error.rule == "unique" for error in result.errors))

    def test_check_null_passes_but_unsupported_check_blocks_persistence(self) -> None:
        nullable_schema = parse_ddl("CREATE TABLE items (id INT PRIMARY KEY, score INT CHECK (score >= 1));")
        nullable_draft = _draft(nullable_schema, {"items": [{"id": 1, "score": None}]})
        self.assertTrue(validate_dataset(nullable_schema, nullable_draft).is_valid)

        unsupported_schema = parse_ddl("CREATE TABLE items (id INT PRIMARY KEY, score INT CHECK (ABS(score) > 0));")
        unsupported_draft = _draft(unsupported_schema, {"items": [{"id": 1, "score": 2}]})
        result = validate_dataset(unsupported_schema, unsupported_draft)
        self.assertFalse(result.is_valid)
        self.assertIn("Unsupported CHECK", result.errors[0].message)

    def test_safe_check_compilation_quotes_columns_and_literals(self) -> None:
        sql = compile_postgres_check("rating >= 1 AND state IN ('A', 'B')", ["rating", "state"])
        self.assertEqual(sql, '(("rating" >= 1) AND ("state" IN (\'A\', \'B\')))')


if __name__ == "__main__":
    unittest.main()
