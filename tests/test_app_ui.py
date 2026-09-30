"""Smoke checks for the stable Streamlit navigation and generation entry screen."""

import unittest
from pathlib import Path

try:
    from streamlit.testing.v1 import AppTest
except ModuleNotFoundError:  # pragma: no cover - system Python may omit app dependencies
    AppTest = None


@unittest.skipIf(AppTest is None, "Streamlit app dependencies are not installed.")
class AppUiTests(unittest.TestCase):
    def test_data_generation_navigation_and_talk_placeholder_render(self) -> None:
        app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
        app.run()

        self.assertFalse(app.exception)
        self.assertEqual(app.sidebar.title[0].value, "Data Assistant")
        self.assertEqual(app.radio[0].options, ["Data Generation", "Talk to your data"])
        self.assertEqual(app.title[0].value, "Data Generation")
        self.assertEqual(app.text_area[0].label, "Prompt")
        self.assertEqual(app.file_uploader[0].label, "Upload DDL schema")
        self.assertEqual(app.button[0].label, "Generate")
        self.assertIn("stDeployButton", app.markdown[0].value)

        app.radio[0].set_value("Talk to your data").run()

        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "Talk to your data")
        self.assertIn("stage 10", app.info[0].value)
