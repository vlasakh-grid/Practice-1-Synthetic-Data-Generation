"""Streamlit entry point for DDL upload and synthetic data workflows."""

import hashlib
import os
from dataclasses import replace

from dotenv import load_dotenv
import streamlit as st
from sqlalchemy import text

from dataset_repository import DatasetRepository, DatasetRepositoryError, InvalidDatasetError, StoredDataset
from domain.dependency_planner import plan_generation
from domain.ddl_parser import DDLParseError, parse_ddl
from domain.draft_generation import DraftDataset, DraftGenerationError, GenerationConfig, GenerationProgress, generate_draft
from domain.validation import ValidationResult, validate_dataset
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


def _render_validation(result: ValidationResult) -> None:
    """Show every constraint error rather than only the first database error."""

    if result.is_valid:
        st.success("Validation passed: this draft satisfies all parsed constraints.")
    else:
        st.error(f"Validation found {len(result.errors)} constraint error(s). The dataset cannot be saved.")
        st.dataframe([error.as_dict() for error in result.errors], hide_index=True, use_container_width=True)


def _invalid_demo_draft(schema, draft: DraftDataset) -> DraftDataset:
    """Return a non-persisted draft with one deliberate validation failure."""

    target_table = next((table for table in schema.tables if table.primary_key), schema.tables[0])
    rows = {name: [dict(row) for row in table_rows] for name, table_rows in draft.rows_by_table.items()}
    if rows[target_table.name]:
        field = target_table.primary_key[0] if target_table.primary_key else target_table.columns[0].name
        rows[target_table.name][0][field] = None
    return replace(draft, rows_by_table={name: tuple(table_rows) for name, table_rows in rows.items()})


def _render_dataset_preview(schema, dataset, *, caption: str, key_prefix: str) -> None:
    table_names = [table.name for table in schema.tables]
    if not table_names:
        return
    selected_table = st.selectbox("Preview table", table_names, key=f"{key_prefix}-preview-table")
    st.caption(f"{len(dataset.rows_for(selected_table))} rows in {selected_table}. {caption}")
    st.dataframe(dataset.rows_for(selected_table), hide_index=True, use_container_width=True)


def _render_draft_generation(schema, schema_digest: str, repository: DatasetRepository | None) -> None:
    """Render draft generation, validation, and explicit persistence controls."""

    plan = plan_generation(schema)
    if st.session_state.get("draft_schema_digest") != schema_digest:
        st.session_state.pop("draft_dataset", None)
        st.session_state.pop("draft_schema_digest", None)

    st.subheader("Draft dataset")
    st.caption("Validate a draft before explicitly saving it as the current PostgreSQL dataset.")
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
        validation = validate_dataset(schema, draft)
        _render_validation(validation)
        if st.button("Load invalid validation demo", key="invalid-draft-demo"):
            st.session_state["draft_dataset"] = _invalid_demo_draft(schema, draft)
            st.rerun()
        _render_dataset_preview(schema, draft, caption="In-memory draft; changes are not saved yet.", key_prefix="draft")

        if repository is None:
            st.info("Configure PostgreSQL to save a validated dataset.")
        else:
            if st.button("Save dataset", disabled=not validation.is_valid, type="primary"):
                try:
                    saved_at = repository.save(schema, draft, schema_digest)
                    restored = repository.load_current()
                except InvalidDatasetError as error:
                    _render_validation(error.result)
                except DatasetRepositoryError as error:
                    st.error(str(error))
                else:
                    st.session_state["persisted_dataset"] = restored
                    st.success(f"Current dataset saved at {saved_at:%Y-%m-%d %H:%M:%S %Z}.")


def _repository_from_environment() -> DatasetRepository | None:
    database_url = os.getenv("DATABASE_URL")
    return DatasetRepository.from_url(database_url) if database_url else None


def _restore_persisted_dataset(repository: DatasetRepository | None) -> StoredDataset | None:
    """Load once per Streamlit session so a restart needs no DDL re-upload."""

    if repository is None:
        return None
    if "persisted_dataset" not in st.session_state and (
        "persisted_dataset_checked" not in st.session_state or "persisted_dataset_restore_error" in st.session_state
    ):
        try:
            st.session_state["persisted_dataset"] = repository.load_current()
            st.session_state.pop("persisted_dataset_restore_error", None)
        except DatasetRepositoryError as error:
            st.session_state["persisted_dataset_restore_error"] = str(error)
        finally:
            st.session_state["persisted_dataset_checked"] = True
    return st.session_state.get("persisted_dataset")


st.set_page_config(page_title="Data Assistant", page_icon="🗃️", layout="wide")
st.title("Data Assistant")
st.caption("Upload a schema to inspect the constraints that will guide data generation.")

uploaded_ddl = st.file_uploader(
    "DDL schema",
    type=["sql", "ddl", "txt"],
    help="MySQL-like CREATE TABLE statements are supported.",
)
repository = _repository_from_environment()
persisted_dataset = _restore_persisted_dataset(repository)
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
        _render_draft_generation(schema, hashlib.sha256(ddl_bytes).hexdigest(), repository)

if uploaded_ddl is None and persisted_dataset is not None:
    st.subheader("Current saved dataset")
    st.caption(f"Restored from PostgreSQL at {persisted_dataset.saved_at:%Y-%m-%d %H:%M:%S %Z}.")
    _render_dataset_preview(
        persisted_dataset.schema,
        persisted_dataset,
        caption="Restored from PostgreSQL.",
        key_prefix="persisted",
    )

if repository is None:
    st.info("PostgreSQL is not configured yet. DDL parsing is available without it.")
else:
    try:
        with repository.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        st.warning(f"PostgreSQL is unavailable: {error}")
    else:
        st.success("Connected to PostgreSQL container.")
        if st.session_state.get("persisted_dataset_restore_error"):
            st.warning(f"Current dataset could not be restored: {st.session_state['persisted_dataset_restore_error']}")
