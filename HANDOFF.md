# Current Status

## Completed

- Stages 10 and 11 are complete. **Talk to your data** now keeps history only
  in the active Streamlit session, clears it when the saved dataset changes,
  streams Gemini's final explanation, and shows the exact compact evidence
  returned by its approved analytics calls.
- The public chat boundary is `domain.data_chat.parse_operation()` and
  `validate_question()`, with only `lookup_schema`, `aggregate`, and
  `retrieve_rows` permitted. Questions are capped at 1,000 characters, four
  calls, 50 rows/groups, 1,024 response tokens, and a three-second statement
  timeout; raw SQL, DDL/DML, credential-seeking, and whole-dataset requests
  are refused before Gemini or PostgreSQL access.
- `application.data_chat_service.DataChatService` and
  `dataset_repository.AnalyticsRepository` are new public application and
  infrastructure interfaces. The latter executes only validated,
  parameterized operations through `ANALYTICS_DATABASE_URL` in a read-only
  transaction. `GeminiAnalyticsChat` exposes exactly the three function calls
  and does not trace questions, tool arguments, result rows, URLs, or secrets.
- Fresh Docker volumes now create isolated non-superuser writer/reader roles.
  The writer grants `synthetic_reader` (or the configured reader role) only
  `USAGE` and `SELECT` on each recreated `generated_data` schema. README and
  the in-app guide provide setup, safety, and demo instructions.

## Verification

- Command: `.venv/bin/python -m unittest -v`
- Result: 45 tests passed, including chat policy, function calling, reader
  grants, read-only timeout/query behavior, tool-call cap, and Streamlit chat
  evidence rendering.
- Command: `.venv/bin/python -m compileall -q app.py application ui domain tests dataset_repository.py integration_readiness.py llm.py`
- Result: completed successfully.
- Command: `docker compose config --quiet`
- Result: configuration validated.
- Command: `git diff --check`
- Result: completed successfully.
- Manual scenario still required with Docker Desktop, a fresh `postgres_data`
  volume, Vertex AI credentials, and Langfuse credentials: save a multi-table
  dataset; ask a count, grouped aggregate, and ≤10-row question; compare the
  evidence with the preview; then try UPDATE/DROP, a credential request, and
  an entire-dataset request. Confirm refusals leave data unchanged; restart
  Streamlit and confirm data persists while chat history is empty. Preserve
  the prior Stage 7–9 DDL, validation, quick-edit, and export scenarios.

## Known Limitations

- End-to-end Docker/browser and live Gemini/Langfuse verification require
  local Docker Desktop, Vertex AI access, and Langfuse credentials; they were
  not run in this sandbox.
- Reader/writer roles are created only when PostgreSQL initializes a new
  volume. Existing local volumes need the documented `docker compose down -v`
  reset, which removes their generated data.
- Analytics deliberately supports one table, equality filters, and no joins or
  arbitrary predicates. It does not execute user- or model-provided SQL.

## Next Steps

1. Perform the documented live Docker demonstration and verify the configured
   reader role cannot write outside the app.
2. No unimplemented delivery stages remain; future work can expand analytics
   operations only by extending the typed policy, tests, and reader-role
   boundary together.

## Important Files

- `domain/data_chat.py` — safety policy, limits, typed analytical operations,
  and schema validation.
- `application/data_chat_service.py`, `llm.py`, and `ui/talk_to_data.py` —
  chat orchestration, Gemini function calling/streaming, and session UI.
- `dataset_repository.py`, `compose.yaml`, and `docker/init/01-create-app-roles.sh`
  — reader enforcement and Docker role initialization.
- `README.md` and `tests/test_data_chat.py` — configuration/demo guide and
  safety/regression coverage.
