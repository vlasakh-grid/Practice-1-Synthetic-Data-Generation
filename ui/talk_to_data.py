"""Session-only Streamlit experience for safe conversations with saved data."""

from __future__ import annotations

from typing import Any

import streamlit as st

from application.data_chat_service import ChatExecutionError, ChatUnavailableError
from application.runtime import AppRuntime
from domain.data_chat import ChatSafetyError


_HISTORY_KEY = "data-chat-history"
_DATASET_KEY = "data-chat-dataset-identity"


def render_talk_to_your_data(runtime: AppRuntime) -> None:
    """Render a bounded, evidence-backed conversation over the saved dataset."""

    st.title("Talk to your data")
    _render_usage_guide()
    current = runtime.persisted_dataset
    if current is None:
        st.info("Save a dataset in Data Generation before starting an analysis conversation.")
        st.caption("Chat history is session-only and is never saved to PostgreSQL.")
        return

    _ensure_current_dataset(current)
    title, clear = st.columns((5, 1))
    with title:
        st.caption(
            f"Analyzing the dataset saved at {current.saved_at:%Y-%m-%d %H:%M:%S %Z}. "
            "The chat cannot modify it."
        )
    with clear:
        if st.button("Clear chat", key="clear-data-chat"):
            st.session_state[_HISTORY_KEY] = []
            st.rerun()

    for message in _history():
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            _render_evidence(message.get("evidence", ()))

    question = st.chat_input("Ask about the saved dataset")
    if question is None:
        return
    _append_message("user", question)
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        _answer_question(runtime, current, question)


def _answer_question(runtime: AppRuntime, current, question: str) -> None:
    if runtime.chat_service is None:
        message = "Chat is unavailable because its read-only analytics service is not configured."
        st.error(message)
        _append_message("assistant", message)
        return
    history = tuple({"role": item["role"], "content": item["content"]} for item in _history()[:-1])
    try:
        prepared = runtime.chat_service.prepare_answer(current, question, history)
        response = st.write_stream(prepared.text_stream)
        message = response if isinstance(response, str) else "".join(str(value) for value in response)
    except ChatSafetyError as error:
        message = str(error)
        st.warning(message)
        _append_message("assistant", message)
        return
    except (ChatUnavailableError, ChatExecutionError) as error:
        message = str(error)
        st.error(message)
        _append_message("assistant", message)
        return
    except Exception:
        message = "The assistant could not complete that analysis. Please try a simpler question."
        st.error(message)
        _append_message("assistant", message)
        return
    _render_evidence(prepared.evidence)
    _append_message("assistant", message, prepared.evidence)


def _ensure_current_dataset(current) -> None:
    identity = (current.schema_digest, current.saved_at.isoformat())
    if st.session_state.get(_DATASET_KEY) != identity:
        st.session_state[_DATASET_KEY] = identity
        st.session_state[_HISTORY_KEY] = []


def _history() -> list[dict[str, Any]]:
    return st.session_state.setdefault(_HISTORY_KEY, [])


def _append_message(role: str, content: str, evidence: tuple[dict[str, Any], ...] = ()) -> None:
    _history().append({"role": role, "content": content, "evidence": evidence})


def _render_evidence(evidence) -> None:
    for result in evidence:
        if result["kind"] == "schema":
            st.caption("Schema used for this answer")
            st.json(result["tables"], expanded=False)
            continue
        label = "Calculated result" if result["kind"] == "aggregate" else "Retrieved rows"
        st.caption(label)
        st.dataframe(result["rows"], hide_index=True, use_container_width=True)


def _render_usage_guide() -> None:
    with st.expander("How to use this tab"):
        st.markdown(
            "Ask focused analytical questions about the currently saved synthetic dataset. "
            "For example: `How many Orders are there?`, `What is the average rating by restaurant?`, "
            "or `Show 10 customers from Austin.`\n\n"
            "The assistant can inspect the schema, calculate bounded aggregates, and retrieve up to 50 rows. "
            "It cannot run SQL, export all data, reveal credentials, or make any database changes. "
            "Each question is limited to 1,000 characters and at most four read-only operations."
        )
