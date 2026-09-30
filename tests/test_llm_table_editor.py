from unittest.mock import patch
import unittest

from domain.ddl_parser import parse_ddl
from domain.table_editing import TableEditError, TableEditRequest
from llm import GeminiTableEditor


class GeminiTableEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = parse_ddl("CREATE TABLE items (id INT PRIMARY KEY, title TEXT NOT NULL, active BOOLEAN);").table("items")
        self.request = TableEditRequest(
            table=self.table,
            rows=({"id": 1, "title": "Original", "active": True},),
            instruction="Make the title friendlier.",
            temperature=1.1,
            max_output_tokens=1024,
        )

    def test_prompt_and_response_schema_are_scoped_to_the_selected_table(self) -> None:
        with patch("llm.generate_json", return_value={"rows": [{"id": 1, "title": "Friendly", "active": True}]}) as generate:
            rows = GeminiTableEditor().edit(self.request)

        self.assertEqual(rows[0]["title"], "Friendly")
        prompt, response_schema = generate.call_args.args
        self.assertIn("Make the title friendlier.", prompt)
        self.assertIn('"id": 1', prompt)
        self.assertEqual(
            set(response_schema["properties"]["rows"]["items"]["properties"]),
            {"id", "title", "active"},
        )
        self.assertEqual(generate.call_args.kwargs["temperature"], 1.1)
        self.assertEqual(generate.call_args.kwargs["max_output_tokens"], 1024)

    def test_invalid_structured_response_is_reported(self) -> None:
        with patch("llm.generate_json", return_value={}):
            with self.assertRaisesRegex(TableEditError, "rows array"):
                GeminiTableEditor().edit(self.request)


if __name__ == "__main__":
    unittest.main()
