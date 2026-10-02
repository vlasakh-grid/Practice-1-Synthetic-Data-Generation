# Practice-1-Synthetic-Data-Generation

A Dockerized Streamlit assistant that generates valid synthetic data from DDL, lets users revise and export it, and answers bounded analytical questions about the one saved PostgreSQL dataset.

## Documentation

- [Implementation plan](docs/implementation-plan.md)
- [Application architecture skill](skills/app-architecture/SKILL.md)
- [Original task](task/task.md)

## Docker Desktop setup

1. Install and start Docker Desktop.
2. Copy `.env.example` to `.env`. Before the first startup, replace the three `change-me-before-starting` database passwords with distinct local values.
3. The default `SEMANTIC_GENERATOR=local` runs deterministic draft generation with no Vertex AI or Langfuse access. To use Gemini instead, set `SEMANTIC_GENERATOR=gemini`, then set `GOOGLE_CLOUD_PROJECT`, optionally change the Vertex AI location/model, and set the Langfuse variables in `.env`.
4. When using `SEMANTIC_GENERATOR=gemini` in Docker, create the ignored `secrets/` folder, place a minimally privileged service-account JSON file there as `vertex-service-account.json`, and set `GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/vertex-service-account.json`. The compose file mounts this directory read-only. For a host-local Gemini run, `gcloud auth application-default login` is also supported by Vertex AI ADC.
5. Run `docker compose up --build`, then open [http://localhost:8501](http://localhost:8501).

PostgreSQL data lives in the `postgres_data` Docker volume; no host PostgreSQL installation is required. The initial database setup creates a non-superuser writer role and a separate `synthetic_reader` role. The app uses the writer for generation/editing and the reader only for Talk to your data.

The role-init script runs only for a new PostgreSQL volume. If this project was started before the reader role was added, stop it and run `docker compose down -v` before the next `docker compose up --build`. This removes the old local generated dataset, so export it first if needed.

## Vertex AI and Langfuse

Gemini uses the Google GenAI SDK with Vertex AI authentication only when `SEMANTIC_GENERATOR=gemini`. The configured identity needs permission to call the selected Gemini model in the configured GCP project. Langfuse is used for model-workflow observability in that mode; configure `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and optionally `LANGFUSE_HOST`. Never commit `.env`, the `secrets/` directory, service-account JSON, or API keys. The UI and Langfuse chat trace exclude database URLs, credentials, raw tool arguments, and returned data rows.

## Generate, save, edit, and export

1. In **Data Generation**, upload one of the supplied `.ddl`, `.sql`, or `.txt` schemas, enter an optional prompt, choose parameters, and select **Generate**.
2. Review the per-table draft and validation results. **Save dataset** becomes available only after every parsed constraint passes; saving atomically replaces the current dataset.
3. Optionally apply a **Quick edit** to the selected saved table. Primary and foreign keys remain unchanged, and the complete candidate dataset is validated before persistence.
4. Download the selected table as CSV or the whole saved dataset as a ZIP.

Use **Load invalid validation demo** after generation to inspect validation errors. It never writes to PostgreSQL. A saved dataset is restored after a Streamlit restart without re-uploading DDL.

## Talk to your data

Open **Talk to your data** after saving a dataset. Chat history lasts only for the active Streamlit session and is cleared automatically when the saved dataset changes. Example questions:

- `How many Orders are there?`
- `What is the average rating by restaurant?`
- `Show 10 customers from Austin.`

Gemini can call only three typed read-only operations: schema lookup, a bounded aggregate, and a bounded row retrieval. Results appear as compact evidence tables below the streamed answer. Each question is limited to 1,000 characters, at most four operations, 50 retrieved rows, 50 aggregate groups, 1,024 response tokens, and a three-second database statement timeout.

The chat refuses SQL text, DDL/DML, configuration or credential requests, and requests for the entire dataset. It never accepts model-produced SQL. The database transaction is read-only and the reader role has no DDL/DML or metadata-write privilege, so a refused or failed request cannot alter generated data.

## End-to-end demo guide

1. Start Docker Desktop and `docker compose up --build`; confirm the app opens.
2. Upload `task/restrurants_schema.ddl`, generate a small draft, save it, and show that validation passes.
3. Switch previews between tables, revise one table with Quick edit, then show the saved CSV and ZIP download controls.
4. Open **Talk to your data**. Ask a count, a grouped aggregate, and a request for no more than 10 rows; compare each evidence table with the preview.
5. Ask `UPDATE Orders SET status = 'cancelled'`, ask for a database password, and ask for the entire dataset. Show the friendly refusal in each case.
6. Return to Data Generation and confirm the preview is unchanged. Restart the Streamlit app: the dataset remains, while the chat history is empty.

## Local UI without Docker or PostgreSQL

For a draft-only local demo, set the following in `.env` (or omit it; `local`
is the default):

```env
SEMANTIC_GENERATOR=local
```

This mode does not contact Vertex AI or Langfuse. It supports DDL parsing,
dependency planning, deterministic draft generation, previews, and validation.
It intentionally does not save datasets, edit saved tables, export saved data,
or answer data-chat questions because PostgreSQL is not configured. Prompt and
temperature values do not change deterministic placeholder text.

Use the project virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Leave `DATABASE_URL` and `ANALYTICS_DATABASE_URL` unset for this draft-only
mode. For the complete host-local workflow, set those URLs for a local
PostgreSQL instance. Set `SEMANTIC_GENERATOR=gemini` to enable Gemini-powered
generation; editing and data chat
also require configured Vertex AI credentials. The `streamlit` executable is
provided by `requirements.txt`; it is not expected to exist on a fresh system
Python.
