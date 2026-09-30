"""Streamlit entry point for DDL upload and synthetic data workflows."""

import hashlib
import os

from dotenv import load_dotenv
import streamlit as st
from sqlalchemy import create_engine, text

from domain.dependency_planner import plan_generation
from domain.ddl_parser import DDLParseError, parse_ddl
from domain.draft_generation import DraftGenerationError, GenerationConfig, GenerationProgress, generate_draft
from integration_readiness import inspect_integration_readiness
from llm import GeminiSemanticValueGenerator

load_dotenv()


def _render_generation_plan(schema) -> None:
    """Render the deterministic plan without coupling the planner to Streamlit."""

    plan = plan_generation(schema)
    st.subheader("Generation plan")
    if plan.is_supported:
        st.success("The schema has a safe generation plan.")
    else:
        st.error("This schema contains a cycle that needs a special generation strategy.")

    for number, phase in enumerate(plan.phases, start=1):
        if phase.kind == "create":
            st.markdown(f"**Phase {number}: create seed rows**")
            st.write(", ".join(phase.tables))
        else:
            st.markdown(f"**Phase {number}: populate deferred foreign keys**")
            st.dataframe(
                [
                    {
                        "Source table": relationship.source_table,
                        "Source columns": ", ".join(relationship.source_columns),
                        "Referenced table": relationship.referenced_table,
                        "Referenced columns": ", ".join(relationship.referenced_columns),
                    }
                    for relationship in phase.relationships
                ],
                hide_index=True,
                use_container_width=True,
            )

    if plan.cycles:
        st.markdown("**Detected cycles**")
        for cycle in plan.cycles:
            tables = " → ".join((*cycle.tables, cycle.tables[0]))
            if cycle.supported:
                st.info(f"{tables}: {cycle.status}")
            else:
                st.warning(f"{tables}: {cycle.status}")


def _render_integration_readiness() -> None:
    """Render local configuration status without contacting Gemini or Langfuse."""

    st.subheader("Integration readiness")
    st.caption("Configuration only — no network requests are made and secrets are never displayed.")
    for check in inspect_integration_readiness():
        details = " · ".join(f"{label}: {value}" for label, value in check.details.items())
        if check.configured:
            st.success(f"{check.name}: configured — {details}")
        else:
            st.warning(f"{check.name}: missing {', '.join(check.missing_variables)} — {details}")


def _render_draft_generation(schema, schema_digest: str) -> None:
    """Render the session-only draft controls and its table preview."""

    plan = plan_generation(schema)
    if st.session_state.get("draft_schema_digest") != schema_digest:
        st.session_state.pop("draft_dataset", None)
        st.session_state.pop("draft_schema_digest", None)

    st.subheader("Draft dataset")
    st.caption("Drafts stay only in this browser session and are not yet saved to PostgreSQL.")
    with st.form("draft-generation-form"):
        instruction = st.text_area(
            "Generation instruction",
            placeholder="For example: generate a family-friendly restaurant dataset for Austin, Texas.",
        )
        parameters = st.columns(3)
        with parameters[0]:
            temperature = st.slider("Temperature", min_value=0.0, max_value=2.0, value=0.7, step=0.1)
        with parameters[1]:
            max_output_tokens = st.number_input(
                "Max tokens", min_value=256, max_value=8192, value=4096, step=256
            )
        with parameters[2]:
            rows_per_table = st.number_input(
                "Rows per table", min_value=1, max_value=100, value=10, step=1
            )
        submitted = st.form_submit_button("Generate draft", disabled=not plan.is_supported, type="primary")

    if not plan.is_supported:
        st.warning("Draft generation is unavailable until the unsupported foreign-key cycle is resolved.")
    elif submitted:
        progress = st.progress(0, text="Preparing draft generation.")
        status = st.status("Preparing draft generation.", expanded=True)

        def report(event: GenerationProgress) -> None:
            status.update(label=event.message, state="running", expanded=True)
            if event.total_steps:
                progress.progress(event.completed_steps / event.total_steps, text=event.message)

        try:
            draft = generate_draft(
                schema,
                GenerationConfig(
                    instruction=instruction,
                    temperature=temperature,
                    max_output_tokens=int(max_output_tokens),
                    rows_per_table=int(rows_per_table),
                ),
                GeminiSemanticValueGenerator(),
                on_progress=report,
            )
        except DraftGenerationError as error:
            st.session_state.pop("draft_dataset", None)
            st.session_state.pop("draft_schema_digest", None)
            progress.empty()
            status.update(label="Draft generation failed.", state="error", expanded=False)
            st.error(str(error))
        else:
            st.session_state["draft_dataset"] = draft
            st.session_state["draft_schema_digest"] = schema_digest
            progress.progress(1.0, text="Draft generation complete.")
            status.update(label="Draft generation complete.", state="complete", expanded=False)
            st.success("Draft dataset is ready for preview.")

    draft = st.session_state.get("draft_dataset")
    if draft is not None and st.session_state.get("draft_schema_digest") == schema_digest:
        table_names = [table.name for table in schema.tables]
        selected_table = st.selectbox("Preview table", table_names, key="draft-preview-table")
        st.caption(f"{len(draft.rows_for(selected_table))} in-memory rows in {selected_table}.")
        st.dataframe(draft.rows_for(selected_table), hide_index=True, use_container_width=True)


st.set_page_config(page_title="Data Assistant", page_icon="🗃️", layout="wide")
st.title("Data Assistant")
st.caption("Upload a schema to inspect the constraints that will guide data generation.")

uploaded_ddl = st.file_uploader(
    "DDL schema",
    type=["sql", "ddl", "txt"],
    help="MySQL-like CREATE TABLE statements are supported.",
)
if uploaded_ddl is not None:
    try:
        ddl_bytes = uploaded_ddl.getvalue()
        schema = parse_ddl(ddl_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        st.error("The uploaded file must be UTF-8 encoded text.")
    except DDLParseError as error:
        st.error(f"The DDL could not be parsed: {error}")
    else:
        st.success(f"Parsed {len(schema.tables)} tables.")
        overview = [
            {
                "Table": table.name,
                "Columns": len(table.columns),
                "Primary key": ", ".join(table.primary_key) or "-",
                "Foreign keys": len(table.foreign_keys),
            }
            for table in schema.tables
        ]
        st.dataframe(overview, hide_index=True, use_container_width=True)
        with st.expander("Parsed schema details"):
            st.json(schema.as_dict())
        _render_generation_plan(schema)
        _render_integration_readiness()
        _render_draft_generation(schema, hashlib.sha256(ddl_bytes).hexdigest())

database_url = os.getenv("DATABASE_URL")
if not database_url:
    st.info("PostgreSQL is not configured yet. DDL parsing is available without it.")
else:
    try:
        engine = create_engine(database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        st.warning(f"PostgreSQL is unavailable: {error}")
    else:
        st.success("Connected to PostgreSQL container.")
