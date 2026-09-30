"""Gemini and Langfuse integration used by the data assistant.

The client uses Vertex AI authentication through Application Default
Credentials. Credentials themselves are never read from or stored in code.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from typing import Any

from google import genai
from google.genai import types
from langfuse import Langfuse

from domain.draft_generation import SemanticGenerationRequest


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def create_gemini_client() -> genai.Client:
    """Create a Vertex AI Gemini client using local ADC credentials."""

    return genai.Client(
        vertexai=True,
        project=_required_env("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )


def create_langfuse_client() -> Langfuse:
    """Create a Langfuse client when observability is configured."""

    return Langfuse(
        public_key=_required_env("LANGFUSE_PUBLIC_KEY"),
        secret_key=_required_env("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )


def generate_json(
    prompt: str,
    response_schema: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_output_tokens: int = 4096,
) -> dict[str, Any]:
    """Generate one structured JSON response and trace it in Langfuse."""

    langfuse = create_langfuse_client()
    generation = langfuse.start_observation(
        name="gemini-structured-generation",
        as_type="generation",
        model=model,
        input=prompt,
        metadata={"response_schema": response_schema},
    )

    try:
        client = create_gemini_client()
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
        result = json.loads(response.text)
        generation.update(output=result).end()
        langfuse.flush()
        return result
    except Exception as error:
        generation.update(status_message=str(error), level="ERROR").end()
        langfuse.flush()
        raise


def stream_json(
    prompt: str,
    response_schema: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_output_tokens: int = 4096,
) -> Iterator[str]:
    """Stream one structured JSON response while tracing the completed result."""

    langfuse = create_langfuse_client()
    generation = langfuse.start_observation(
        name="gemini-streaming-structured-generation",
        as_type="generation",
        model=model,
        input=prompt,
        metadata={"response_schema": response_schema},
    )
    chunks: list[str] = []
    try:
        client = create_gemini_client()
        response_stream = client.models.generate_content_stream(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
        for chunk in response_stream:
            text = chunk.text or ""
            chunks.append(text)
            yield text
        generation.update(output=json.loads("".join(chunks))).end()
        langfuse.flush()
    except Exception as error:
        generation.update(status_message=str(error), level="ERROR").end()
        langfuse.flush()
        raise


class GeminiSemanticValueGenerator:
    """Gemini adapter for the domain draft generator's semantic-value port."""

    def generate(
        self,
        request: SemanticGenerationRequest,
        *,
        on_text: Callable[[str], None] | None = None,
    ) -> list[dict[str, Any]]:
        response_schema = {
            "type": "OBJECT",
            "properties": {
                "rows": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {column.name: {"type": "STRING"} for column in request.columns},
                        "required": [column.name for column in request.columns],
                    },
                }
            },
            "required": ["rows"],
        }
        fields = ", ".join(f"{column.name} ({column.raw_type})" for column in request.columns)
        instruction = request.instruction.strip() or "Use realistic, varied synthetic values."
        prompt = (
            "Generate synthetic values for one database table. "
            "Return exactly the requested JSON shape and row count; do not include primary keys, foreign keys, "
            "enums, identifiers, or commentary. Values must be fictional and must not be real personal data.\n"
            f"Table: {request.table.name}\n"
            f"Rows required: {request.row_count}\n"
            f"Semantic fields: {fields}\n"
            f"User instruction: {instruction}"
        )
        raw_json = "".join(
            self._stream(
                prompt,
                response_schema,
                temperature=request.temperature,
                max_output_tokens=request.max_output_tokens,
                on_text=on_text,
            )
        )
        payload = json.loads(raw_json)
        rows = payload.get("rows")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Gemini did not return a JSON object with a rows array")
        return rows

    @staticmethod
    def _stream(
        prompt: str,
        response_schema: dict[str, Any],
        *,
        temperature: float,
        max_output_tokens: int,
        on_text: Callable[[str], None] | None,
    ) -> Iterator[str]:
        for text in stream_json(
            prompt,
            response_schema,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ):
            if on_text is not None:
                on_text(text)
            yield text


def stream_text(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_output_tokens: int = 4096,
) -> Iterator[str]:
    """Stream Gemini text while recording the complete generation in Langfuse."""

    langfuse = create_langfuse_client()
    generation = langfuse.start_observation(
        name="gemini-streaming-generation",
        as_type="generation",
        model=model,
        input=prompt,
    )
    chunks: list[str] = []

    try:
        client = create_gemini_client()
        response_stream = client.models.generate_content_stream(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
        )
        for chunk in response_stream:
            text = chunk.text or ""
            chunks.append(text)
            yield text
        generation.update(output="".join(chunks)).end()
        langfuse.flush()
    except Exception as error:
        generation.update(status_message=str(error), level="ERROR").end()
        langfuse.flush()
        raise
