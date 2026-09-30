"""Streamlit entry point for the synthetic-data generation workflow."""

import hashlib
import os
from dataclasses import replace

from dotenv import load_dotenv
import streamlit as st

from dataset_repository import DatasetRepository, DatasetRepositoryError, InvalidDatasetError, StoredDataset
from domain.dependency_planner import plan_generation
from domain.ddl_parser import DDLParseError, parse_ddl
from domain.draft_generation import DraftDataset, DraftGenerationError, GenerationConfig, GenerationProgress, generate_draft
from domain.validation import ValidationResult, validate_dataset
from integration_readiness import inspect_integration_readiness
from llm import GeminiSemanticValueGenerator

load_dotenv()


def _hide_streamlit_deploy_button() -> None:
    """Hide only Streamlit's hosting control, not the rest of its toolbar."""

    st.markdown(
        "<style>[data-testid='stDeployButton'] { display: none !important; }</style>",
        unsafe_allow_html=True,
    )


def _render_sidebar() -> str:
    """Render the stable application navigation shared by future workflow pages."""

    with st.sidebar:
        st.title("Data Assistant")
        return st.radio(
            "Navigation",
            ("Data Generation", "Talk to your data"),
            label_visibility="collapsed",
        )


def _render_generation_plan(schema) -> None:
    """Render the deterministic plan without coupling the planner to Streamlit."""

    plan = plan_generation(schema)
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
    """Show one selected table from a draft or a saved dataset."""

    table_names = [table.name for table in schema.tables]
    if not table_names:
        return
    header, selector = st.columns((4, 1))
    with header:
        st.subheader("Data preview")
    with selector:
        selected_table = st.selectbox("Preview table", table_names, key=f"{key_prefix}-preview-table")
    st.caption(f"{len(dataset.rows_for(selected_table))} rows in {selected_table}. {caption}")
    st.dataframe(dataset.rows_for(selected_table), hide_index=True, use_container_width=True)


def _clear_stale_draft(schema_digest: str) -> None:
    """Keep a session draft tied to exactly one uploaded schema."""

    if st.session_state.get("draft_schema_digest") != schema_digest:
        st.session_state.pop("draft_dataset", None)
        st.session_state.pop("draft_schema_digest", None)


def _generate_draft(
    schema,
    schema_digest: str,
    instruction: str,
    temperature: float,
    max_output_tokens: int,
    rows_per_table: int,
) -> None:
    """Generate a full draft while rendering progress in the current UI page."""

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


def _render_current_dataset_status(repository: DatasetRepository | None, persisted_dataset: StoredDataset | None) -> None:
    """Keep persistence status visible without distracting from generation controls."""

    st.subheader("Current dataset")
    if persisted_dataset is not None:
        st.success(
            f"Saved in PostgreSQL at {persisted_dataset.saved_at:%Y-%m-%d %H:%M:%S %Z} "
            f"({len(persisted_dataset.schema.tables)} tables)."
        )
    elif repository is None:
        st.info("PostgreSQL is not configured. You can generate a draft, but cannot save it yet.")
    elif st.session_state.get("persisted_dataset_restore_error"):
        st.warning(f"Current dataset could not be restored: {st.session_state['persisted_dataset_restore_error']}")
    else:
        st.info("No saved dataset yet. Generate and validate a draft to save the current dataset.")


def _render_schema_details(schema) -> None:
    """Keep schema diagnostics available without interrupting the main workflow."""

    overview = [
        {
            "Table": table.name,
            "Columns": len(table.columns),
            "Primary key": ", ".join(table.primary_key) or "-",
            "Foreign keys": len(table.foreign_keys),
        }
        for table in schema.tables
    ]
    with st.expander("Schema details"):
        st.dataframe(overview, hide_index=True, use_container_width=True)
        st.json(schema.as_dict())
    with st.expander("Generation plan"):
        _render_generation_plan(schema)
    with st.expander("Integration readiness"):
        _render_integration_readiness()


def _render_draft_and_saved_preview(
    schema,
    schema_digest: str,
    repository: DatasetRepository | None,
    persisted_dataset: StoredDataset | None,
) -> None:
    """Validate a draft and surface the saved result once persistence succeeds."""

    draft = st.session_state.get("draft_dataset")
    if draft is None or st.session_state.get("draft_schema_digest") != schema_digest:
        return

    validation = validate_dataset(schema, draft)
    saved_preview = persisted_dataset is not None and persisted_dataset.schema_digest == schema_digest and validation.is_valid
    if saved_preview:
        _render_dataset_preview(
            persisted_dataset.schema,
            persisted_dataset,
            caption=f"Saved in PostgreSQL at {persisted_dataset.saved_at:%Y-%m-%d %H:%M:%S %Z}.",
            key_prefix="saved",
        )
    else:
        _render_dataset_preview(
            schema,
            draft,
            caption="In-memory draft; changes are not saved yet.",
            key_prefix="draft",
        )
    _render_validation(validation)

    actions, demo = st.columns((1, 1))
    with actions:
        if repository is None:
            st.info("Configure PostgreSQL to save a validated dataset.")
        elif st.button("Save dataset", disabled=not validation.is_valid, type="primary"):
            try:
                repository.save(schema, draft, schema_digest)
                persisted_dataset = repository.load_current()
            except InvalidDatasetError as error:
                _render_validation(error.result)
            except DatasetRepositoryError as error:
                st.error(str(error))
            else:
                st.session_state["persisted_dataset"] = persisted_dataset
                st.rerun()
    with demo:
        if st.button("Load invalid validation demo", key="invalid-draft-demo"):
            st.session_state["draft_dataset"] = _invalid_demo_draft(schema, draft)
            st.rerun()


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


def _render_data_generation_page(repository: DatasetRepository | None, persisted_dataset: StoredDataset | None) -> None:
    """Render the DDL-to-saved-preview user path from the target design."""

    st.title("Data Generation")
    st.caption("Describe the dataset, upload its DDL schema, then generate and save a validated preview.")
    _render_current_dataset_status(repository, persisted_dataset)

    st.subheader("Generate data")
    instruction = st.text_area(
        "Prompt",
        placeholder="For example: generate a family-friendly restaurant dataset for Austin, Texas.",
    )
    uploaded_ddl = st.file_uploader(
        "Upload DDL schema",
        type=["sql", "ddl", "txt"],
        help="MySQL-like CREATE TABLE statements are supported.",
    )

    schema = None
    schema_digest = None
    if uploaded_ddl is not None:
        try:
            ddl_bytes = uploaded_ddl.getvalue()
            schema = parse_ddl(ddl_bytes.decode("utf-8"))
            schema_digest = hashlib.sha256(ddl_bytes).hexdigest()
        except UnicodeDecodeError:
            st.error("The uploaded file must be UTF-8 encoded text.")
        except DDLParseError as error:
            st.error(f"The DDL could not be parsed: {error}")
        else:
            _clear_stale_draft(schema_digest)
            st.success(f"Parsed {len(schema.tables)} tables.")

    parameters = st.columns(3)
    with parameters[0]:
        temperature = st.slider("Temperature", min_value=0.0, max_value=2.0, value=0.7, step=0.1)
    with parameters[1]:
        max_output_tokens = st.number_input("Max tokens", min_value=256, max_value=8192, value=4096, step=256)
    with parameters[2]:
        rows_per_table = st.number_input("Rows per table", min_value=1, max_value=100, value=10, step=1)

    plan = plan_generation(schema) if schema is not None else None
    if st.button("Generate", type="primary", disabled=plan is None or not plan.is_supported):
        _generate_draft(schema, schema_digest, instruction, temperature, max_output_tokens, rows_per_table)
    if plan is not None and not plan.is_supported:
        st.warning("Draft generation is unavailable until the unsupported foreign-key cycle is resolved.")

    if schema is not None:
        _render_draft_and_saved_preview(schema, schema_digest, repository, persisted_dataset)
        _render_schema_details(schema)
    elif persisted_dataset is not None:
        _render_dataset_preview(
            persisted_dataset.schema,
            persisted_dataset,
            caption="Restored from PostgreSQL. Upload a DDL file to generate a replacement.",
            key_prefix="persisted",
        )


def _render_talk_to_your_data_placeholder(persisted_dataset: StoredDataset | None) -> None:
    """Reserve the second navigation destination for the stage-10 chat workflow."""

    st.title("Talk to your data")
    st.info("Conversational analysis will be available in stage 10. This page does not send requests or query the database yet.")
    if persisted_dataset is None:
        st.caption("Generate and save a dataset in Data Generation so it will be ready for analysis.")
    else:
        st.caption(
            f"A current dataset with {len(persisted_dataset.schema.tables)} tables is ready for the future chat workflow."
        )


st.set_page_config(page_title="Data Assistant", page_icon="🗃️", layout="wide", initial_sidebar_state="expanded")
_hide_streamlit_deploy_button()
repository = _repository_from_environment()
persisted_dataset = _restore_persisted_dataset(repository)
page = _render_sidebar()

if page == "Data Generation":
    _render_data_generation_page(repository, persisted_dataset)
else:
    _render_talk_to_your_data_placeholder(persisted_dataset)
