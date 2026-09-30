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
    """Render sidebar navigation without exposing Streamlit radio controls."""

    pages = (
        ("Data Generation", ":material/storage:  Data Generation", "data-generation"),
        ("Talk to your data", ":material/forum:  Talk to your data", "talk-to-your-data"),
    )
    state_key = "selected-page"
    if state_key not in st.session_state:
        st.session_state[state_key] = pages[0][0]
    active_key = next(key for page, _, key in pages if page == st.session_state[state_key])

    st.markdown(
        f"""
        <style>
        section[data-testid="stSidebar"],
        section[data-testid="stSidebar"] > div,
        section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
            background: #ffffff !important;
        }}
        section[data-testid="stSidebar"] {{
            min-width: 19rem !important;
            width: 19rem !important;
        }}
        section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
            padding: 1rem 1.5rem 0 !important;
        }}
        section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {{
            display: none !important;
        }}
        section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{
            padding-top: 1rem !important;
        }}
        section[data-testid="stSidebar"] h1 {{
            color: #172033 !important;
            font-size: 1.5rem !important;
            font-weight: 650 !important;
            letter-spacing: -0.02em;
            margin: 0.25rem 0 1.25rem;
        }}
        section[data-testid="stSidebar"] .stButton > button {{
            background: transparent !important;
            border: 0 !important;
            border-radius: 0.55rem !important;
            box-shadow: none !important;
            color: #273247 !important;
            font-size: 0.98rem !important;
            font-weight: 400 !important;
            justify-content: flex-start !important;
            min-height: 2.95rem !important;
            padding: 0.58rem 0.72rem !important;
            text-align: left !important;
        }}
        section[data-testid="stSidebar"] .stButton > button:hover {{
            background: #f5f6f8 !important;
        }}
        section[data-testid="stSidebar"] .st-key-sidebar-nav-{active_key} button {{
            background: #eef0f3 !important;
            color: #172033 !important;
            font-weight: 600 !important;
        }}
        section[data-testid="stSidebar"] .stButton > button [data-testid="stMarkdownContainer"] p {{
            color: inherit !important;
            margin: 0 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.sidebar:
        st.title("Data Assistant")
        for page, label, key in pages:
            st.button(
                label,
                key=f"sidebar-nav-{key}",
                use_container_width=True,
                on_click=lambda value=page: st.session_state.__setitem__(state_key, value),
            )
    return st.session_state[state_key]


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
