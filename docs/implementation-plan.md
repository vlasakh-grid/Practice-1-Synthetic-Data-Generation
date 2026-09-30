# Implementation Plan

## Goal

Build a Dockerized conversational data assistant that generates valid synthetic data from provided DDL schemas and lets the user analyze the current dataset through a chat interface.

## Delivery Principle

Every stage must add a user-visible capability that can be manually verified in a locally running Streamlit application. Automated tests and documentation updates are completed within the relevant stage, not deferred to a separate non-functional task.

## Subtasks

1. [x] **Prepare the environment**
   - Set up the Python project, Docker Compose, and a PostgreSQL container with persistent local storage.
   - Configure the application to connect to PostgreSQL through environment variables and the Docker service name, without requiring a host PostgreSQL installation.
   - Document reproducible Docker Desktop startup.
   - Manual check: start the application and confirm the PostgreSQL connection status in the UI.

2. [x] **Configure Gemini and Langfuse**
   - Connect Gemini 2.0 Flash or newer through the Google GenAI SDK and Vertex AI.
   - Provide structured output, streaming, function calling where appropriate, and Langfuse tracing for LLM workflows.
   - The first UI diagnostic for these configured integrations is delivered in stage 4.

3. [x] **Implement DDL parsing**
   - Accept `.sql`, `.ddl`, and `.txt` uploads.
   - Parse tables, columns, data types, nullability, primary and foreign keys, unique constraints, checks, defaults, and enum values.
   - Support the MySQL-like syntax used in all three supplied schemas while producing a PostgreSQL-compatible internal representation.
   - Manual check: upload any supplied DDL file and inspect its table overview and parsed constraints.

4. [x] **Show dependency planning and integration readiness**
   - Build a foreign-key dependency model with a stable generation order, self-references, and strongly connected components.
   - After a DDL upload, display generation phases, deferred relationships/cycles, and a safe Gemini/Langfuse readiness diagnostic without exposing secrets.
   - Manual check: upload all three supplied schemas; verify parent-before-child phases and the explicit `Employees` / `Departments` / `Library_Branches` cycle in the library schema.

5. [x] **Generate a draft dataset and preview it**
   - Add a natural-language instruction, temperature, max tokens, and rows-per-table controls.
   - Use Gemini structured output to generate records in dependency phases, show streaming progress, and present an in-memory draft preview per table.
   - Generate cyclic records and their deferred foreign-key values in separate phases.
   - Manual check: generate drafts for each supplied schema and switch between table previews.

6. [x] **Validate, persist, and restore a dataset**
   - Validate explicit primary-key, foreign-key, required-field, unique, enum, and check constraints with errors identifying the table, row, field, and failed rule.
   - Persist only valid datasets to PostgreSQL transactionally and restore the current dataset from PostgreSQL after an application restart.
   - Manual check: generate and save a dataset, restart Streamlit, and verify that its data remains available; verify the error presentation for an invalid result.

7. [ ] **Complete the Data Generation workflow UI**
   - Arrange the existing workflow around the structure in `task/sample.png`: sidebar navigation, DDL upload, prompt, parameters, Generate action, table selector, preview, and current-dataset status.
   - Preserve the generation and persistence contracts from earlier stages.
   - Manual check: complete the DDL-upload-to-saved-preview workflow entirely through the target screen.

8. [ ] **Edit a selected table through text instructions**
   - Add quick-edit instructions and a Submit action for the selected table.
   - Apply a Gemini structured change, revalidate the whole dataset, persist it atomically, and refresh the preview.
   - Manual check: request a change to one table and confirm the changed rows and valid related data.

9. [ ] **Export the current dataset**
   - Download the selected persisted table as CSV.
   - Download the complete persisted dataset as a ZIP archive of CSV files.
   - Manual check: download both formats, unpack the archive, and compare its tables and rows with the UI.

10. [ ] **Add the Talk to your data tab**
    - Add session-only chat history and streaming Gemini responses over the current PostgreSQL dataset.
    - Use function calling only for predefined read-only operations: schema lookup, bounded aggregates, and bounded row retrieval.
    - Manual check: ask analytical questions after generation and verify answers against the data preview.

11. [ ] **Harden chat safety and complete the demo guide**
    - Enforce read-only database access, an allowlist of analytical operations, result/time limits, blocked DDL/DML, credential protection, and user-friendly errors.
    - Add an in-app usage guide and complete the README with Docker Desktop, Vertex AI, Langfuse, and end-to-end demo instructions.
    - Manual check: confirm a normal analytics question succeeds while data-changing, secret-seeking, and oversized requests are safely rejected without modifying the dataset.

## Agreed Defaults

- UI framework: Streamlit.
- Database: local PostgreSQL in Docker Desktop; no cloud PostgreSQL is required.
- Dataset lifetime: persisted in the local PostgreSQL container; chat history is limited to the current application session.
- Input schemas: all three DDL files in `task/` must be supported.
- Data validation: enforce only constraints explicitly present in the DDL; do not invent domain rules.
- UI fidelity: preserve the workflow shown in `task/sample.png`, adapted to Streamlit.
