# Current Status

## Completed

- Stage 7 is complete: the Streamlit UI now has sidebar navigation, a target
  Data Generation workflow, a persisted-dataset status, and an explicit
  stage-10 placeholder for Talk to your data.
- The main workflow order is prompt, DDL upload, parameters, Generate, table
  preview, validation, and Save dataset. Schema, dependency, and integration
  diagnostics are available in expanders.
- The Streamlit Deploy control is hidden with the scoped
  `[data-testid='stDeployButton']` style. Generation, validation, and
  PostgreSQL persistence contracts are unchanged.
- Public interfaces are unchanged.

## Verification

- Command: `.venv/bin/python -m unittest -v`
- Result: 26 tests passed, including the Streamlit UI smoke test for sidebar
  navigation, the generation controls, Deploy-button styling, and the Talk
  placeholder.
- Command: `.venv/bin/python -m compileall -q app.py domain tests dataset_repository.py integration_readiness.py llm.py`
- Result: completed successfully.
- Command: `docker compose config --quiet`
- Result: configuration validated.
- Manual scenario: start the app, confirm Deploy is hidden; upload each DDL,
  set the prompt and parameters, generate, switch preview tables, save, and
  restart Streamlit to verify the restored dataset. Open Talk to your data and
  verify its stage-10 placeholder. Preserve the invalid-draft and library-cycle
  scenarios from stage 6.

## Known Limitations

- PostgreSQL transaction and browser persistence flows require Docker Desktop.
- Local Streamlit socket startup was previously blocked by the execution
  sandbox; use the documented local or Docker workflow for browser verification.
- CHECK validation supports only the existing safe subset, and Vertex AI plus
  Langfuse credentials remain required for real semantic generation.

## Next Steps

1. Implement stage 8: quick text edits for the selected table, whole-dataset
   revalidation, and atomic persistence.
2. Implement stage 9 CSV and ZIP exports from the persisted current dataset.

## Important Files

- `app.py` - sidebar navigation, Data Generation workflow, and stage-10 placeholder.
- `dataset_repository.py` - atomic save and restore of the current dataset.
- `domain/validation.py` - constraint validation used before persistence.
- `docs/implementation-plan.md` - completed-stage tracking.
