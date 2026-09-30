"""Smoke checks for the stable Streamlit navigation and generation entry screen."""

import unittest
from pathlib import Path

try:
    from streamlit.testing.v1 import AppTest
except ModuleNotFoundError:  # pragma: no cover - system Python may omit app dependencies
    AppTest = None


@unittest.skipIf(AppTest is None, "Streamlit app dependencies are not installed.")
class AppUiTests(unittest.TestCase):
    def test_data_generation_navigation_and_chat_prerequisite_render(self) -> None:
        app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
        app.run()

        self.assertFalse(app.exception)
        self.assertEqual(app.sidebar.title[0].value, "Data Assistant")
        self.assertEqual(len(app.radio), 0)
        self.assertEqual(
            [button.label for button in app.sidebar.button],
            [":material/storage:  Data Generation", ":material/forum:  Talk to your data"],
        )
        self.assertEqual(app.title[0].value, "Data Generation")
        self.assertEqual(app.text_area[0].label, "Prompt")
        self.assertEqual(app.file_uploader[0].label, "Upload DDL schema")
        self.assertEqual(next(button.label for button in app.button if button.label == "Generate"), "Generate")
        self.assertIn("stDeployButton", app.markdown[0].value)

        app.sidebar.button[1].click().run()

        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "Talk to your data")
        self.assertIn("Save a dataset", app.info[0].value)
        self.assertEqual(app.expander[0].label, "How to use this tab")

    def test_saved_dataset_shows_the_selected_table_editor_and_exports(self) -> None:
        app = AppTest.from_string(
            '''
from datetime import datetime, timezone
from application.dataset_service import DatasetService
from application.runtime import AppRuntime
from dataset_repository import StoredDataset
from domain.ddl_parser import parse_ddl
from ui.data_generation import render_data_generation

class UnusedGenerator:
    def generate(self, request, *, on_text=None):
        raise AssertionError("not used")

schema = parse_ddl("CREATE TABLE items (id INT PRIMARY KEY, name TEXT NOT NULL);")
saved = StoredDataset(schema, {"items": ({"id": 1, "name": "Original"},)}, "digest", datetime(2026, 9, 30, tzinfo=timezone.utc))
runtime = AppRuntime(repository=object(), dataset_service=DatasetService(None, UnusedGenerator()), persisted_dataset=saved)
render_data_generation(runtime)
'''
        )
        app.run()

        self.assertFalse(app.exception)
        self.assertIn("Quick edit instruction", [area.label for area in app.text_area])
        self.assertIn("Submit", [button.label for button in app.button])
        self.assertEqual(
            [button.label for button in app.get("download_button")],
            ["Download items.csv", "Download complete dataset (.zip)"],
        )

    def test_in_memory_draft_does_not_offer_exports(self) -> None:
        app = AppTest.from_string(
            '''
from application.dataset_service import DatasetService
from application.runtime import AppRuntime
from domain.ddl_parser import parse_ddl
from domain.dependency_planner import plan_generation
from domain.draft_generation import DraftDataset, GenerationConfig
from ui.data_generation import _render_draft_and_saved_preview
import streamlit as st

class UnusedGenerator:
    def generate(self, request, *, on_text=None):
        raise AssertionError("not used")

schema = parse_ddl("CREATE TABLE items (id INT PRIMARY KEY, name TEXT NOT NULL);")
draft = DraftDataset(
    rows_by_table={"items": ({"id": 1, "name": "Draft only"},)},
    plan=plan_generation(schema),
    config=GenerationConfig(rows_per_table=1),
)
st.session_state["draft_dataset"] = draft
st.session_state["draft_schema_digest"] = "draft-digest"
runtime = AppRuntime(repository=object(), dataset_service=DatasetService(None, UnusedGenerator()))
_render_draft_and_saved_preview(runtime, schema, "draft-digest")
'''
        )
        app.run()

        self.assertFalse(app.exception)
        self.assertEqual(app.get("download_button"), [])

    def test_saved_dataset_renders_chat_input_answer_and_evidence(self) -> None:
        app = AppTest.from_string(
            '''
from datetime import datetime, timezone
from application.data_chat_service import PreparedChatAnswer
from application.dataset_service import DatasetService
from application.runtime import AppRuntime
from dataset_repository import StoredDataset
from domain.ddl_parser import parse_ddl
from ui.talk_to_data import render_talk_to_your_data

class UnusedGenerator:
    def generate(self, request, *, on_text=None):
        raise AssertionError("not used")

class Chat:
    def prepare_answer(self, current, question, history):
        return PreparedChatAnswer(
            ({"kind": "aggregate", "columns": ["value"], "rows": [{"value": 1}]},),
            iter(("There is one item.",)),
        )

schema = parse_ddl("CREATE TABLE items (id INT PRIMARY KEY, name TEXT NOT NULL);")
saved = StoredDataset(schema, {"items": ({"id": 1, "name": "One"},)}, "digest", datetime(2026, 9, 30, tzinfo=timezone.utc))
runtime = AppRuntime(repository=object(), dataset_service=DatasetService(None, UnusedGenerator()), chat_service=Chat(), persisted_dataset=saved)
render_talk_to_your_data(runtime)
'''
        )
        app.run()

        self.assertFalse(app.exception)
        self.assertEqual(app.chat_input[0].placeholder, "Ask about the saved dataset")
        self.assertIn("Clear chat", [button.label for button in app.button])

        app.chat_input[0].set_value("How many items?").run()

        self.assertFalse(app.exception)
        self.assertIn("There is one item.", [markdown.value for markdown in app.markdown])
        self.assertEqual(len(app.dataframe), 1)
