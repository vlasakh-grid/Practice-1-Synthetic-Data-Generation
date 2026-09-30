from pathlib import Path
import unittest

from domain.ddl_parser import parse_ddl
from domain.draft_generation import (
    DraftGenerationError,
    GenerationConfig,
    SemanticGenerationRequest,
    generate_draft,
)


TASK_DIR = Path(__file__).parents[1] / "task"


class FakeSemanticGenerator:
    def __init__(self) -> None:
        self.requests: list[SemanticGenerationRequest] = []

    def generate(self, request: SemanticGenerationRequest, *, on_text=None):
        self.requests.append(request)
        if on_text is not None:
            on_text('{"rows":')
        return [
            {column.name: f"{request.table.name} {column.name} {index}" for column in request.columns}
            for index in range(1, request.row_count + 1)
        ]


class FailingSemanticGenerator:
    def generate(self, request: SemanticGenerationRequest, *, on_text=None):
        raise RuntimeError("Vertex AI is unavailable")


class DraftGenerationTests(unittest.TestCase):
    def test_all_supplied_schemas_create_ten_rows_with_stable_keys_and_foreign_keys(self) -> None:
        for path in sorted(TASK_DIR.glob("*.ddl")):
            with self.subTest(schema=path.name):
                schema = parse_ddl(path.read_text())
                draft = generate_draft(schema, GenerationConfig(), FakeSemanticGenerator())

                for table in schema.tables:
                    rows = draft.rows_for(table.name)
                    self.assertEqual(len(rows), 10)
                    for primary_key in table.primary_key:
                        self.assertEqual([row[primary_key] for row in rows], list(range(1, 11)))
                    for foreign_key in table.foreign_keys:
                        referenced = draft.rows_for(foreign_key.referenced_table)
                        valid_keys = {
                            tuple(row[column] for column in foreign_key.referenced_columns) for row in referenced
                        }
                        for row in rows:
                            value = tuple(row[column] for column in foreign_key.columns)
                            self.assertIn(value, valid_keys)

    def test_generation_uses_dependency_plan_order_and_reports_streaming_progress(self) -> None:
        schema = parse_ddl((TASK_DIR / "restrurants_schema.ddl").read_text())
        generator = FakeSemanticGenerator()
        events = []

        generate_draft(schema, GenerationConfig(rows_per_table=2), generator, on_progress=events.append)

        self.assertEqual(
            [event.table for event in events if event.kind == "table_complete"],
            ["Customers", "Delivery_Drivers", "Restaurants", "Menu", "Orders", "Reviews", "Order_Items"],
        )
        self.assertTrue(any(event.message.startswith("Receiving structured values") for event in events))
        self.assertEqual(events[-1].kind, "complete")

    def test_library_cycle_defers_then_populates_all_relationships(self) -> None:
        schema = parse_ddl((TASK_DIR / "library_mgm_schema.ddl").read_text())
        events = []
        draft = generate_draft(schema, GenerationConfig(rows_per_table=3), FakeSemanticGenerator(), on_progress=events.append)

        self.assertLess(
            next(index for index, event in enumerate(events) if event.kind == "deferred_started"),
            next(index for index, event in enumerate(events) if event.kind == "deferred_complete"),
        )
        for relationship in draft.plan.cycles[0].relationships:
            target_values = {
                tuple(row[column] for column in relationship.referenced_columns)
                for row in draft.rows_for(relationship.referenced_table)
            }
            for row in draft.rows_for(relationship.source_table):
                self.assertIn(tuple(row[column] for column in relationship.source_columns), target_values)

    def test_unsupported_cycle_is_rejected_before_the_semantic_gateway_is_called(self) -> None:
        schema = parse_ddl(
            """
            CREATE TABLE alpha (id INT PRIMARY KEY, beta_id INT NOT NULL,
                FOREIGN KEY (beta_id) REFERENCES beta(id));
            CREATE TABLE beta (id INT PRIMARY KEY, alpha_id INT,
                FOREIGN KEY (alpha_id) REFERENCES alpha(id));
            """
        )
        generator = FakeSemanticGenerator()

        with self.assertRaisesRegex(DraftGenerationError, "NOT NULL"):
            generate_draft(schema, GenerationConfig(), generator)
        self.assertEqual(generator.requests, [])

    def test_gateway_failure_does_not_return_a_partial_draft(self) -> None:
        schema = parse_ddl((TASK_DIR / "restrurants_schema.ddl").read_text())

        with self.assertRaisesRegex(DraftGenerationError, "Vertex AI is unavailable"):
            generate_draft(schema, GenerationConfig(), FailingSemanticGenerator())

    def test_semantic_gateway_receives_instruction_and_generation_parameters(self) -> None:
        schema = parse_ddl((TASK_DIR / "restrurants_schema.ddl").read_text())
        generator = FakeSemanticGenerator()

        generate_draft(
            schema,
            GenerationConfig(
                instruction="Family-friendly venues in Austin",
                temperature=1.2,
                max_output_tokens=2048,
                rows_per_table=1,
            ),
            generator,
        )

        self.assertTrue(generator.requests)
        request = generator.requests[0]
        self.assertEqual(request.instruction, "Family-friendly venues in Austin")
        self.assertEqual(request.temperature, 1.2)
        self.assertEqual(request.max_output_tokens, 2048)

if __name__ == "__main__":
    unittest.main()
