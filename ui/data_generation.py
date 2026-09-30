"""Data Generation page and its Streamlit session workflow."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import streamlit as st

from application.runtime import AppRuntime
from dataset_repository import DatasetRepositoryError, InvalidDatasetError
from domain.dependency_planner import plan_generation
from domain.ddl_parser import DDLParseError, parse_ddl
from domain.draft_generation import DraftDataset, DraftGenerationError, GenerationConfig, GenerationProgress
from domain.table_editing import TableEditError
from ui.common import render_dataset_preview, render_validation
from ui.diagnostics import render_schema_details


def _invalid_demo_draft(schema, draft: DraftDataset) -> DraftDataset:
    """Return a non-persisted draft with one deliberate validation failure."""

    target_table = next((table for table in schema.tables if table.primary_key), schema.tables[0])
    rows = {name: [dict(row) for row in table_rows] for name, table_rows in draft.rows_by_table.items()}
    if rows[target_table.name]:
        field = target_table.primary_key[0] if target_table.primary_key else target_table.columns[0].name
        rows[target_table.name][0][field] = None
    return replace(draft, rows_by_table={name: tuple(table_rows) for name, table_rows in rows.items()})


def _clear_stale_draft(schema_digest: str) -> None:
    """Keep a session draft tied to exactly one uploaded schema."""

    if st.session_state.get("draft_schema_digest") != schema_digest:
        st.session_state.pop("draft_dataset", None)
        st.session_state.pop("draft_schema_digest", None)


def _render_current_dataset_status(runtime: AppRuntime) -> None:
    """Keep persistence status visible without distracting from generation controls."""

    st.subheader("Current dataset")
    if runtime.persisted_dataset is not None:
        st.success(
            f"Saved in PostgreSQL at {runtime.persisted_dataset.saved_at:%Y-%m-%d %H:%M:%S %Z} "
            f"({len(runtime.persisted_dataset.schema.tables)} tables)."
        )
    elif runtime.repository is None:
        st.info("PostgreSQL is not configured. You can generate a draft, but cannot save it yet.")
    elif runtime.restore_error:
        st.warning(f"Current dataset could not be restored: {runtime.restore_error}")
    else:
        st.info("No saved dataset yet. Generate and validate a draft to save the current dataset.")


def _generate_draft(runtime: AppRuntime, schema, schema_digest: str, instruction: str, temperature: float, max_output_tokens: int, rows_per_table: int) -> None:
    """Generate a full draft while rendering progress in the current UI page."""

    progress = st.progress(0, text="Preparing draft generation.")
    status = st.status("Preparing draft generation.", expanded=True)

    def report(event: GenerationProgress) -> None:
        status.update(label=event.message, state="running", expanded=True)
        if event.total_steps:
            progress.progress(event.completed_steps / event.total_steps, text=event.message)

    try:
        draft = runtime.dataset_service.generate(
            schema,
            GenerationConfig(
                instruction=instruction,
                temperature=temperature,
                max_output_tokens=int(max_output_tokens),
                rows_per_table=int(rows_per_table),
            ),
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


def _render_draft_and_saved_preview(runtime: AppRuntime, schema, schema_digest: str) -> str | None:
    """Validate a draft and surface the saved result once persistence succeeds."""

    draft = st.session_state.get("draft_dataset")
    if draft is None or st.session_state.get("draft_schema_digest") != schema_digest:
        if runtime.persisted_dataset is None or runtime.persisted_dataset.schema_digest != schema_digest:
            return None
        return render_dataset_preview(
            runtime.persisted_dataset.schema,
            runtime.persisted_dataset,
            caption=f"Saved in PostgreSQL at {runtime.persisted_dataset.saved_at:%Y-%m-%d %H:%M:%S %Z}.",
            key_prefix="saved",
        )

    validation = runtime.dataset_service.validate(schema, draft)
    saved_preview = (
        runtime.persisted_dataset is not None
        and runtime.persisted_dataset.schema_digest == schema_digest
        and validation.is_valid
    )
    if saved_preview:
        selected_table = render_dataset_preview(
            runtime.persisted_dataset.schema,
            runtime.persisted_dataset,
            caption=f"Saved in PostgreSQL at {runtime.persisted_dataset.saved_at:%Y-%m-%d %H:%M:%S %Z}.",
            key_prefix="saved",
        )
    else:
        selected_table = render_dataset_preview(
            schema,
            draft,
            caption="In-memory draft; changes are not saved yet.",
            key_prefix="draft",
        )
    render_validation(validation)

    actions, demo = st.columns((1, 1))
    with actions:
        if runtime.repository is None:
            st.info("Configure PostgreSQL to save a validated dataset.")
        elif st.button("Save dataset", disabled=not validation.is_valid, type="primary"):
            try:
                st.session_state["persisted_dataset"] = runtime.dataset_service.save(schema, draft, schema_digest)
            except InvalidDatasetError as error:
                render_validation(error.result)
            except DatasetRepositoryError as error:
                st.error(str(error))
            else:
                st.rerun()
    with demo:
        if st.button("Load invalid validation demo", key="invalid-draft-demo"):
            st.session_state["draft_dataset"] = _invalid_demo_draft(schema, draft)
            st.rerun()
    return selected_table


def _render_quick_edit(runtime: AppRuntime, selected_table: str, temperature: float, max_output_tokens: int) -> None:
    """Edit the saved selected table while keeping failed candidates out of PostgreSQL."""

    current = runtime.persisted_dataset
    st.subheader("Quick edit")
    st.caption(f"Apply a text instruction to {selected_table}. Row count, primary keys, and foreign keys are preserved.")
    if current is None or runtime.repository is None:
        st.info("Save a dataset in PostgreSQL before applying a quick edit.")
        return

    with st.form("quick-table-edit"):
        instruction = st.text_area(
            "Quick edit instruction",
            placeholder=f"For example: make the {selected_table} entries more family-friendly.",
        )
        submitted = st.form_submit_button("Submit", type="primary")
    if not submitted:
        return
    if not instruction.strip():
        st.warning("Enter an instruction before submitting a table edit.")
        return

    status = st.status(f"Applying edit to {selected_table}.", expanded=False)
    try:
        saved = runtime.dataset_service.apply_edit(
            current,
            selected_table,
            instruction,
            temperature=temperature,
            max_output_tokens=int(max_output_tokens),
        )
    except InvalidDatasetError as error:
        status.update(label="Table edit failed validation; saved data was not changed.", state="error")
        render_validation(error.result)
    except (TableEditError, DatasetRepositoryError, ValueError) as error:
        status.update(label="Table edit was not applied.", state="error")
        st.error(str(error))
    else:
        runtime.persisted_dataset = saved
        st.session_state["persisted_dataset"] = saved
        if st.session_state.get("draft_schema_digest") == saved.schema_digest:
            st.session_state["draft_dataset"] = DraftDataset(
                rows_by_table={name: tuple(dict(row) for row in rows) for name, rows in saved.rows_by_table.items()},
                plan=plan_generation(saved.schema),
                config=GenerationConfig(
                    instruction=instruction,
                    temperature=temperature,
                    max_output_tokens=int(max_output_tokens),
                    rows_per_table=max(1, len(saved.rows_for(selected_table))),
                ),
            )
        status.update(label="Table edit saved in PostgreSQL.", state="complete")
        st.rerun()


def render_data_generation(runtime: AppRuntime) -> None:
    """Render the complete DDL-to-saved-preview workflow."""

    st.title("Data Generation")
    st.caption("Describe the dataset, upload its DDL schema, then generate and save a validated preview.")
    _render_current_dataset_status(runtime)

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

    plan_supported = schema is not None and schema_digest is not None
    if schema is not None:
        plan_supported = plan_generation(schema).is_supported
    if st.button("Generate", type="primary", disabled=not plan_supported):
        _generate_draft(runtime, schema, schema_digest, instruction, temperature, max_output_tokens, rows_per_table)
    if schema is not None and not plan_supported:
        st.warning("Draft generation is unavailable until the unsupported foreign-key cycle is resolved.")

    if schema is not None:
        selected_table = _render_draft_and_saved_preview(runtime, schema, schema_digest)
        if selected_table is not None:
            _render_quick_edit(runtime, selected_table, temperature, int(max_output_tokens))
        render_schema_details(schema)
    elif runtime.persisted_dataset is not None:
        selected_table = render_dataset_preview(
            runtime.persisted_dataset.schema,
            runtime.persisted_dataset,
            caption="Restored from PostgreSQL. Upload a DDL file to generate a replacement.",
            key_prefix="persisted",
        )
        if selected_table is not None:
            _render_quick_edit(runtime, selected_table, temperature, int(max_output_tokens))
