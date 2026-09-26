# Implementation Plan

## Goal

Build a Dockerized conversational data assistant that generates synthetic data from the provided DDL schemas and lets the user analyze the current dataset through a chat interface.

## Status

- [ ] Not started
- [ ] In progress
- [ ] Completed

## Subtasks

1. **Prepare the environment**
   - Set up the Python project, Docker Compose, local PostgreSQL, and environment variables.
   - Add reproducible startup instructions for Docker Desktop.

2. **Configure Gemini and Langfuse**
   - Connect to Gemini 2.0 Flash or newer through the Google GenAI SDK and Vertex AI.
   - Use structured output, streaming, and function calling where appropriate.
   - Add Langfuse tracing for LLM calls and generation workflows.

3. **Implement DDL parsing**
   - Accept `.sql`, `.ddl`, and `.txt` uploads.
   - Parse tables, columns, data types, nullability, primary keys, foreign keys, unique constraints, checks, defaults, and enum values.
   - Support the MySQL-like syntax used in the three supplied schemas while producing a PostgreSQL-compatible internal representation.

4. **Build the schema dependency model**
   - Determine a safe generation order from foreign-key relationships.
   - Handle self-references and circular dependencies such as those in the library schema.

5. **Implement synthetic data generation**
   - Accept a natural-language prompt, model parameters, and rows-per-table.
   - Generate realistic structured records with Gemini.
   - Preserve only the constraints explicitly defined by the DDL.

6. **Validate and persist generated data**
   - Validate primary keys, foreign keys, unique values, required fields, enum values, and check constraints.
   - Load valid results into local PostgreSQL running in Docker.
   - Return actionable validation errors when a generated result is invalid.

7. **Build the Data Generation UI**
   - Reproduce the structure from `task/sample.png`: sidebar navigation, prompt, DDL upload, temperature, max tokens, row count, Generate button, table selector, and preview.

8. **Add text-based table editing**
   - Provide quick-edit instructions for the selected table.
   - Apply the requested change, revalidate the dataset, and refresh the preview.

9. **Add exports**
   - Download an individual table as CSV.
   - Download the complete dataset as a ZIP archive containing CSV files.

10. **Build the Talk to your data tab**
    - Provide a session-only analytical chat over the current generated dataset.
    - Use Gemini to interpret questions and produce answers based on the available data.
    - Keep chat history in the current application session; it may disappear after a page reload.

11. **Apply chat safety controls**
    - Restrict database operations to read-only analysis.
    - Limit result sizes and prevent DDL/DML execution through chat.
    - Hide credentials and return user-friendly errors.

12. **Test and document the project**
    - Test all three supplied DDL schemas, including foreign keys, unique constraints, check constraints, self-references, and circular references.
    - Test generation, editing, preview, CSV/ZIP export, and the analytical chat.
    - Complete the README with setup, configuration, Docker Desktop startup, and demo instructions.

## Agreed Defaults

- UI framework: Streamlit or Gradio, selected during implementation based on the simplest reliable integration.
- Database: local PostgreSQL in Docker Desktop; no cloud PostgreSQL is required.
- Dataset lifetime: available to the running application session and stored in the local PostgreSQL container; chat history is session-only.
- Input schemas: the three DDL files supplied in `task/` must be supported.
- Data validation: enforce constraints explicitly present in the DDL; do not invent additional domain rules.
- UI fidelity: preserve the structure and workflow shown in `task/sample.png`, adapting styling to the selected UI framework.
