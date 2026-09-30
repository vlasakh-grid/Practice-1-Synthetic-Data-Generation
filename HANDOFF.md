# Current Status

## Completed

- Stage 5 is complete: the app generates a session-only draft dataset and
  previews one table at a time.
- Public interfaces added: `generate_draft(schema, config,
  semantic_generator) -> DraftDataset`, `GenerationConfig`,
  `GenerationProgress`, and the mockable `SemanticValueGenerator` port.
- Draft generation follows `DependencyPlan`: local code creates keys, typed
  values, enums, and foreign keys; streamed Gemini structured JSON supplies
  semantic string values; nullable cycle relationships are populated in a
  deferred phase.
- Streamlit exposes instruction, temperature, max tokens, rows per table
  (default `10`), progress, and table preview controls. Drafts are not
  persisted.

## Verification

- Command: `python3 -m unittest -v`
- Result: 18 tests passed, including all supplied schemas, FK integrity,
  deferred cycles, progress events, gateway parameters, and gateway failures.
- Command: `python3 -m compileall -q domain tests app.py integration_readiness.py llm.py`
- Result: compilation completed successfully.
- Manual scenario: run the app through the documented `.venv` command, upload
  each DDL in `task/`, generate with configured Gemini/Vertex AI and Langfuse,
  then switch between table previews. For the library schema, verify deferred
  FKs for `Employees`, `Departments`, and `Library_Branches`.
- Manual result: Streamlit starts locally through `.venv`; the networked
  Gemini generation scenario still requires external credentials and was not
  invoked by automated checks.

## Known Limitations

- Stage 6 validation, PostgreSQL persistence, and dataset restoration are not
  implemented; drafts live only in the current Streamlit session.
- Vertex AI and Langfuse configuration/credentials are required for real
  generation. Unsupported cycles containing internal `NOT NULL` FKs remain
  blocked.
- The parser supports the MySQL-like DDL used in `task/`, not arbitrary SQL.
- Semantic generation is batched in groups of 10; the UI supports up to 100
  rows per table through multiple batches.

## Next Steps

1. Implement stage 6 constraint validation with table, row, field, and rule
   errors.
2. Persist only valid datasets transactionally to PostgreSQL and restore them
   after restart.
3. Keep `DraftDataset` as the input contract for validation and persistence.

## Important Files

- `domain/draft_generation.py` - draft service and semantic gateway contract.
- `domain/dependency_planner.py` - FK generation phases and cycle handling.
- `llm.py` - streamed Gemini structured JSON adapter and Langfuse tracing.
- `app.py` - generation controls, progress, and previews.
- `tests/test_draft_generation.py` - stage 5 coverage.
- `docs/implementation-plan.md` - stage tracking and acceptance scenarios.
