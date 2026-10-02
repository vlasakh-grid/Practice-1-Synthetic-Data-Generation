# Current Status

## Completed

- Stage 12 is complete. Local draft-only mode is now the default in both
  Streamlit and Docker Compose; `SEMANTIC_GENERATOR=local` provides
  deterministic text values without creating a Gemini client or contacting
  Vertex AI or Langfuse. Set `SEMANTIC_GENERATOR=gemini` only to opt in to
  Vertex AI. The local path preserves DDL parsing, dependency planning,
  PK/FK/enum/type validation, and preview generation for all supplied schemas.
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
- Result: 52 tests passed, including local deterministic generation and
  validation for all supplied schemas, chat policy, function calling, reader
  grants, read-only timeout/query behavior, tool-call cap, and Streamlit chat
  evidence rendering.
- Command: `.venv/bin/python -m compileall -q app.py application ui domain tests dataset_repository.py integration_readiness.py llm.py`
- Result: completed successfully.
- Command: `docker compose config --quiet`
- Result: configuration validated.
- Command: `git diff --check`
- Result: completed successfully.
- Manual local scenario: set `SEMANTIC_GENERATOR=local`, leave
  `DATABASE_URL` and `ANALYTICS_DATABASE_URL` unset, run
  `python -m streamlit run app.py`, upload each supplied DDL, and confirm
  Generate shows the in-memory preview and passing validation without Vertex
  AI credentials. This has not been browser-verified in the sandbox.
- Manual scenario still required with Docker Desktop, a fresh `postgres_data`
  volume, Vertex AI credentials, and Langfuse credentials: save a multi-table
  dataset; ask a count, grouped aggregate, and ≤10-row question; compare the
  evidence with the preview; then try UPDATE/DROP, a credential request, and
  an entire-dataset request. Confirm refusals leave data unchanged; restart
  Streamlit and confirm data persists while chat history is empty. Preserve
  the prior Stage 7–9 DDL, validation, quick-edit, and export scenarios.

## Known Limitations

- Local deterministic mode creates generic placeholder text and ignores the
  prompt and temperature. It does not support persistence, quick edit, export,
  or data chat without PostgreSQL; quick edit and data chat additionally need
  Gemini when PostgreSQL is configured.
- End-to-end Docker/browser and live Gemini/Langfuse verification require
  local Docker Desktop, Vertex AI access, and Langfuse credentials; they were
  not run in this sandbox.
- Reader/writer roles are created only when PostgreSQL initializes a new
  volume. Existing local volumes need the documented `docker compose down -v`
  reset, which removes their generated data.
- Analytics deliberately supports one table, equality filters, and no joins or
  arbitrary predicates. It does not execute user- or model-provided SQL.

## Next Steps

1. Perform the documented local draft-only scenario without Vertex AI, then
   the live Docker demonstration when Vertex AI credentials are available.
2. No unimplemented delivery stages remain; future work can expand analytics
   operations only by extending the typed policy, tests, and reader-role
   boundary together.

## Important Files

- `domain/data_chat.py` — safety policy, limits, typed analytical operations,
  and schema validation.
- `domain/draft_generation.py` and `application/bootstrap.py` — deterministic
  local semantic generator and the `SEMANTIC_GENERATOR` mode selection.
- `application/data_chat_service.py`, `llm.py`, and `ui/talk_to_data.py` —
  chat orchestration, Gemini function calling/streaming, and session UI.
- `dataset_repository.py`, `compose.yaml`, and `docker/init/01-create-app-roles.sh`
  — reader enforcement and Docker role initialization.
- `README.md`, `tests/test_draft_generation.py`, and `tests/test_bootstrap.py`
  — local-run guide and fallback-generation regression coverage.
