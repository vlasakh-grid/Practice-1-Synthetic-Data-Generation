import unittest

from integration_readiness import inspect_integration_readiness


class IntegrationReadinessTests(unittest.TestCase):
    def test_default_local_mode_does_not_require_vertex_configuration(self) -> None:
        readiness = inspect_integration_readiness({})

        self.assertTrue(readiness[0].configured)
        self.assertEqual(readiness[0].details["Mode"], "Local deterministic")
        self.assertFalse(readiness[1].configured)
        self.assertEqual(readiness[1].missing_variables, ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"))
        self.assertNotIn("LANGFUSE_SECRET_KEY", readiness[1].details)

    def test_configured_status_shows_only_safe_metadata(self) -> None:
        readiness = inspect_integration_readiness(
            {
                "SEMANTIC_GENERATOR": "gemini",
                "GOOGLE_CLOUD_PROJECT": "demo-project",
                "GEMINI_MODEL": "gemini-2.5-flash",
                "GOOGLE_CLOUD_LOCATION": "us-central1",
                "LANGFUSE_PUBLIC_KEY": "public-secret-value",
                "LANGFUSE_SECRET_KEY": "private-secret-value",
                "LANGFUSE_HOST": "https://example.langfuse.test",
            }
        )

        self.assertTrue(all(check.configured for check in readiness))
        self.assertEqual(readiness[0].details["Project"], "demo-project")
        self.assertEqual(readiness[1].details, {"Host": "https://example.langfuse.test"})

    def test_local_generator_does_not_require_vertex_configuration(self) -> None:
        readiness = inspect_integration_readiness({"SEMANTIC_GENERATOR": "local"})

        self.assertTrue(readiness[0].configured)
        self.assertEqual(readiness[0].name, "Semantic generator")
        self.assertEqual(
            readiness[0].details,
            {"Mode": "Local deterministic", "Vertex AI": "Not used"},
        )


if __name__ == "__main__":
    unittest.main()
