"""Gemini and Langfuse integration used by the data assistant.

The client uses Vertex AI authentication through Application Default
Credentials. Credentials themselves are never read from or stored in code.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

from google import genai
from google.genai import types
from langfuse import Langfuse


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
