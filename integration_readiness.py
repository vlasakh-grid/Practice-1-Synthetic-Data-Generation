"""Local, secret-safe configuration diagnostics for external integrations."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Mapping


@dataclass(frozen=True)
class IntegrationReadiness:
    name: str
    configured: bool
    details: dict[str, str]
    missing_variables: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def inspect_integration_readiness(env: Mapping[str, str] | None = None) -> tuple[IntegrationReadiness, ...]:
    """Inspect configuration only; this function never contacts external services."""

    values = os.environ if env is None else env
    project = values.get("GOOGLE_CLOUD_PROJECT", "").strip()
    model = values.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    location = values.get("GOOGLE_CLOUD_LOCATION", "us-central1").strip() or "us-central1"
    gemini = IntegrationReadiness(
        name="Gemini (Vertex AI)",
        configured=bool(project),
        details={"Project": project or "Not set", "Model": model, "Location": location},
        missing_variables=("GOOGLE_CLOUD_PROJECT",) if not project else (),
    )

    public_key = values.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = values.get("LANGFUSE_SECRET_KEY", "").strip()
    host = values.get("LANGFUSE_HOST", "https://cloud.langfuse.com").strip() or "https://cloud.langfuse.com"
    missing = tuple(
        name
        for name, value in (("LANGFUSE_PUBLIC_KEY", public_key), ("LANGFUSE_SECRET_KEY", secret_key))
        if not value
    )
    langfuse = IntegrationReadiness(
        name="Langfuse",
        configured=not missing,
        details={"Host": host},
        missing_variables=missing,
    )
    return gemini, langfuse
