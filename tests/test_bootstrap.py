import os
import unittest
from unittest.mock import patch

from application.bootstrap import _semantic_generator_from_environment
from domain.draft_generation import LocalSemanticValueGenerator
from llm import GeminiSemanticValueGenerator


class BootstrapTests(unittest.TestCase):
    def test_local_semantic_generator_mode_avoids_the_gemini_gateway(self) -> None:
        with patch.dict(os.environ, {"SEMANTIC_GENERATOR": "local"}, clear=True):
            generator, label = _semantic_generator_from_environment()

        self.assertIsInstance(generator, LocalSemanticValueGenerator)
        self.assertEqual(label, "Local deterministic")

    def test_local_is_the_default_semantic_generator(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            generator, label = _semantic_generator_from_environment()

        self.assertIsInstance(generator, LocalSemanticValueGenerator)
        self.assertEqual(label, "Local deterministic")

    def test_gemini_mode_is_explicit(self) -> None:
        with patch.dict(os.environ, {"SEMANTIC_GENERATOR": "gemini"}, clear=True):
            generator, label = _semantic_generator_from_environment()

        self.assertIsInstance(generator, GeminiSemanticValueGenerator)
        self.assertEqual(label, "Gemini (Vertex AI)")

    def test_unknown_semantic_generator_mode_is_rejected(self) -> None:
        with patch.dict(os.environ, {"SEMANTIC_GENERATOR": "unknown"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SEMANTIC_GENERATOR"):
                _semantic_generator_from_environment()


if __name__ == "__main__":
    unittest.main()
