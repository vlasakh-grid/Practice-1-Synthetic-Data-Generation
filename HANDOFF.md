# Current Status

## Completed

- Completed stage 5: in-memory draft generation and per-table preview.
- Added `python-dotenv` to project requirements and documented the host-local
  Streamlit startup path through a `.venv`.
- Streamlit now loads `.env` at startup so local readiness checks can see
  non-secret configuration such as `GOOGLE_CLOUD_PROJECT`.
- Added the public `plan_generation(schema) -> DependencyPlan` interface and
  its `GenerationPhase`, `DependencyCycle`, and `DeferredRelationship` models.
- The planner uses FK dependency graph SCCs and alphabetic ordering within a
  phase; nullable self-references/cycles receive a deferred-update phase.
- Non-nullable cyclic foreign keys are reported as unsupported without a
  special strategy.
- Streamlit now displays generation phases, deferred relationships, cycle
  status, and a local Gemini/Langfuse configuration diagnostic after DDL upload.
- The diagnostic makes no network calls and displays neither credentials nor
  credential-derived values.
- Added the public `generate_draft(schema, config, semantic_generator) ->
  DraftDataset` interface with `GenerationConfig`, `GenerationProgress`, and
  a mockable `SemanticValueGenerator` port.
- Draft generation uses dependency-plan create/deferred phases: local code
  supplies primary keys, foreign keys, enums, type-shaped values, and
  nullable-cycle seed values; Gemini supplies only semantic string fields via
  streamed structured JSON and Langfuse tracing.
- Streamlit now offers an instruction, temperature (default `0.7`), max tokens
  (default `4096`), and rows-per-table (`1–100`, default `10`) form. Completed
  drafts are session-only and can be previewed one table at a time.
- A Gemini, Vertex AI, or Langfuse failure displays an error and clears the
  incomplete draft rather than creating a fallback dataset.

## Verification

- Command: `python3 -m unittest -v`
- Result: all 18 tests passed, including ten-row draft generation for each
  supplied schema, foreign keys, cycle deferral, streamed progress events,
  gateway parameters, and gateway failures.
- Command: `python3 -m compileall -q domain tests app.py integration_readiness.py llm.py`
- Result: compilation completed successfully.
- Manual scenario to preserve: for host-local UI checks, run `python3 -m venv
  .venv`, `source .venv/bin/activate`, `python -m pip install -r
  requirements.txt`, then `python -m streamlit run app.py`.
- Manual scenarios to preserve: upload each DDL in `task/`; verify
  parent-before-child phases and the `Employees` / `Departments` /
  `Library_Branches` deferred cycle. Verify the readiness panel lists only
  configuration status and no secrets.
- Manual result: host-local Streamlit UI checks are confirmed green when run
  through the documented `.venv` startup path.
- Manual check to preserve: upload each DDL in `task/`, use the draft controls
  with the default 10 rows, generate with configured Gemini/Vertex AI and
  Langfuse, then switch between every table preview. For the library schema,
  confirm `Employees`, `Departments`, and `Library_Branches` contain populated
  deferred foreign keys after the progress indicator completes.
- Manual result: the application starts through `.venv` on localhost; the
  networked Gemini generation scenario remains dependent on configured Vertex
  AI and Langfuse credentials and was not invoked during automated checks.

## Known Limitations

- The parser targets the MySQL-like DDL used in `task/`; it is not a complete
  SQL parser.
- Streamlit is a project dependency, not a guaranteed global command. Use the
  documented `.venv` startup path for host-local UI checks.
- Readiness confirms configuration only; it does not validate Vertex ADC,
  Gemini access, Langfuse connectivity, or send traces.
- Drafts are session-only; formal validation, PostgreSQL persistence, and
  restoration remain unimplemented. Cycles with internal `NOT NULL` foreign
  keys remain blocked.
- Gemini semantic batches are limited to 10 rows to keep structured responses
  manageable; the UI permits up to 100 rows by issuing multiple batches.

## Next Steps

1. Implement stage 6 validation with table/row/field/rule error reporting.
2. Persist only valid datasets transactionally to PostgreSQL and restore them
   after application restart.
3. Retain the draft-generation service as the input to validation rather than
   persisting raw Gemini output.

## Important Files

- `domain/dependency_planner.py` - public FK planning model and algorithm.
- `domain/draft_generation.py` - public session-only draft generation service
  and semantic gateway port.
- `integration_readiness.py` - local, secret-safe configuration checks.
- `llm.py` - streamed Gemini structured JSON and the semantic gateway adapter.
- `app.py` - DDL upload, readiness, draft controls, progress, and previews.
- `tests/test_draft_generation.py` - draft ordering, integrity, gateway, and
  deferred-cycle coverage.
- `tests/test_dependency_planner.py` - dependency-plan coverage.
- `tests/test_integration_readiness.py` - readiness privacy coverage.
- `docs/implementation-plan.md` - completed stage tracking.
