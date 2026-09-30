"""Talk to your data page placeholder until the chat stage is implemented."""

from __future__ import annotations

import streamlit as st

from application.runtime import AppRuntime


def render_talk_to_your_data(runtime: AppRuntime) -> None:
    """Reserve the second navigation destination for the stage-10 chat workflow."""

    st.title("Talk to your data")
    st.info(
        "Conversational analysis will be available in stage 10. "
        "This page does not send requests or query the database yet."
    )
    if runtime.persisted_dataset is None:
        st.caption("Generate and save a dataset in Data Generation so it will be ready for analysis.")
    else:
        st.caption(
            f"A current dataset with {len(runtime.persisted_dataset.schema.tables)} tables "
            "is ready for the future chat workflow."
        )
