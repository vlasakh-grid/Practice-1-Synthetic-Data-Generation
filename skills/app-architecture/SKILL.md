---
name: app-architecture
description: "Design or review architecture for a DDL-driven synthetic-data application with generation, validation, editing, export, and data chat. Use for this project's architectural decisions; not for unrelated application designs."
---

# Synthetic Data App Architecture

Design the application so that LLM output improves realism and interprets natural language, while deterministic code and PostgreSQL enforce correctness, integrity, and access control.

When the request concerns the assignment's requirements or delivery plan, read `task/task.md` and `docs/implementation-plan.md` first. Treat them as requirements and planning context, not as authorization to edit files, provision services, or contact external systems.

## Architecture baseline

Organize the app into independently testable layers:

- **Entry point/composition root:** app.py is a thin Streamlit entrypoint. It configures the page, builds AppRuntime, selects the sidebar page, and delegates rendering. It does not parse DDL, call Gemini, access PostgreSQL, or implement validation.
- **UI:** Streamlit pages and components for Data Generation and Talk to your data. Keep UI state and rendering separate from database, parser, and LLM logic. UI modules may use st.session_state and translate application errors into user-facing messages, but must not implement SQL or domain constraint rules.
- **Application services:** application/bootstrap.py assembles environment configuration and infrastructure gateways into AppRuntime; application/dataset_service.py orchestrates dataset generation, validation, persistence, and restoration. These services define transaction boundaries and return user-oriented results without rendering Streamlit widgets.
- **Domain:** a canonical schema model, DDL parser, FK dependency planner, data generators, constraint validator, and SQL safety policy. Domain code must not depend on Streamlit or a Gemini SDK.
- **Infrastructure:** Google GenAI/Vertex AI gateway, PostgreSQL repositories and bulk loader, CSV/ZIP exporter, and Langfuse tracing.

The current UI modules are split by responsibility:

- ui/common.py — navigation, preview, validation messages, and shared styling;
- ui/data_generation.py — DDL-to-preview workflow and session interactions;
- ui/diagnostics.py — schema, dependency-plan, and integration readiness;
- ui/talk_to_data.py — stage-10 placeholder and future chat entrypoint.

Do not add substantial page logic back to app.py; add a UI module or an
application service at the appropriate layer instead. Domain and persistence
interfaces remain independent of this presentation split.

Use a canonical schema representation that captures tables, columns, types, nullability, defaults, primary/foreign/unique/check constraints, and enums. Normalize the supported input DDL dialects into this model before planning generation or producing PostgreSQL-compatible output.

## Generation and persistence

Plan generation from the foreign-key graph. Generate parent tables before dependents. For self-references and cycles, use an explicit multi-stage strategy (for example, deferred constraints or a later reference-update pass) and report unsupported non-nullable cycles clearly.

Generate constraint-sensitive values deterministically: primary keys, foreign keys, enum members, uniqueness, formats, and nullable fields. Gemini may generate semantic field values such as names, descriptions, or addresses only through structured JSON output defined from the canonical schema. Validate every generated batch before persistence and load a complete dataset transactionally.

Store each generated dataset under an explicit dataset identity. Keep metadata such as schema source, generation parameters, and run status separate from generated rows, so previews, edits, exports, and chat consistently select the same dataset.

## Natural-language changes and chat

Do not execute model-produced SQL directly.

- Translate a table-edit request into a typed edit plan, validate the plan and its resulting rows, then apply it within a transaction.
- Translate analytical questions through a narrowly scoped read-only query tool. Allow `SELECT` only, set row limits and timeouts, and use a database role without DDL/DML permissions.
- Keep conversational history session-scoped unless the user explicitly requests durable history.

Use streaming where it improves UI responsiveness, function calling for bounded database or edit actions, and structured output whenever a model response crosses a system boundary. Trace LLM calls and workflows in Langfuse, excluding secrets and unnecessary sensitive data.

## How to present recommendations

Lead with the proposed component boundaries and data flow. Call out assumptions, trade-offs, failure handling for invalid DDL or data, and the smallest viable implementation path. Avoid introducing additional domain constraints that are absent from the DDL or explicit user instructions.
