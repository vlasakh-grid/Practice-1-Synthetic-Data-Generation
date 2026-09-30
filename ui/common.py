"""Reusable Streamlit controls shared by application pages."""

from __future__ import annotations

from typing import Any

import streamlit as st

from domain.schema import Schema
from domain.validation import ValidationResult


def hide_streamlit_deploy_button() -> None:
    """Hide only Streamlit's hosting control, not the rest of its toolbar."""

    st.markdown(
        "<style>[data-testid='stDeployButton'] { display: none !important; }</style>",
        unsafe_allow_html=True,
    )


def render_sidebar() -> str:
    """Render the stable application navigation shared by workflow pages."""

    with st.sidebar:
        st.title("Data Assistant")
        return st.radio(
            "Navigation",
            ("Data Generation", "Talk to your data"),
            label_visibility="collapsed",
        )


def render_validation(result: ValidationResult) -> None:
    """Show every constraint error rather than only the first database error."""

    if result.is_valid:
        st.success("Validation passed: this draft satisfies all parsed constraints.")
    else:
        st.error(f"Validation found {len(result.errors)} constraint error(s). The dataset cannot be saved.")
        st.dataframe([error.as_dict() for error in result.errors], hide_index=True, use_container_width=True)


def render_dataset_preview(schema: Schema, dataset: Any, *, caption: str, key_prefix: str) -> str | None:
    """Show one selected table from a draft or a saved dataset and return its name."""

    table_names = [table.name for table in schema.tables]
    if not table_names:
        return None
    header, selector = st.columns((4, 1))
    with header:
        st.subheader("Data preview")
    with selector:
        selected_table = st.selectbox("Preview table", table_names, key=f"{key_prefix}-preview-table")
    st.caption(f"{len(dataset.rows_for(selected_table))} rows in {selected_table}. {caption}")
    st.dataframe(dataset.rows_for(selected_table), hide_index=True, use_container_width=True)
    return selected_table
