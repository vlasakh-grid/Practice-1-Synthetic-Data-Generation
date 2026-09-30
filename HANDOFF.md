# Current Status

## Completed

- Stage 8 is complete: a saved dataset can be edited through an instruction
  for the table currently selected in the preview.
- Gemini receives only that table's schema and current rows, and must return a
  complete same-order replacement. The domain layer rejects changed row count,
  fields, primary keys, and foreign keys before validation.
- `DatasetService.edit_current(...)` returns a candidate `DraftDataset` plus
  whole-dataset `ValidationResult`; `apply_edit(...)` persists only a valid
  candidate through the existing atomic PostgreSQL replacement transaction.
- The Quick edit UI uses existing temperature and max-token controls. Failed
  Gemini responses and validation failures leave the persisted dataset intact.
- Stage 7 UI, generation, validation, persistence, and Talk-to-your-data
  placeholder behavior remain available.
- The sidebar now follows `task/sample.png`: white surface, compact title,
  material navigation icons, a rounded active-item highlight, and button-based
  navigation with no radio controls rendered.

## Verification

- Command: `.venv/bin/python -m unittest -v`
- Result: 32 tests passed, including quick-edit UI, candidate isolation,
  invalid-edit persistence protection, and Gemini request-schema tests.
- Command: `.venv/bin/python -m compileall -q app.py application ui domain tests dataset_repository.py integration_readiness.py llm.py`
- Result: completed successfully.
- Command: `docker compose config --quiet`
- Result: configuration validated.
- Command: `.venv/bin/python -m unittest tests.test_app_ui -v`
- Result: 2 UI smoke tests passed, including sidebar labels and icon formatting.
- Manual scenario to run with Docker Desktop: save a generated dataset, select
  a table, enter a content-only quick-edit instruction, and click Submit.
  Confirm only selected rows change, related rows remain valid, and the edit
  remains after restarting Streamlit. Also request an invalid value and verify
  that validation errors appear with no saved-data change. Preserve the stage-7
  DDL-upload-to-saved-preview, invalid-draft, and library-cycle scenarios.

## Known Limitations

- PostgreSQL transaction and browser persistence flows require Docker Desktop;
  the new end-to-end Gemini edit was not browser-verified in this sandbox.
- Quick edits intentionally preserve row count, primary keys, and foreign keys;
  they do not add/delete records or relink existing relationships.
- CHECK validation supports only the existing safe subset, and Vertex AI plus
  Langfuse credentials remain required for real generation and editing.

## Next Steps

1. Implement stage 9 CSV and ZIP exports from the persisted current dataset.
2. Implement stage 10 session-only, read-only Talk to your data chat.

## Important Files

- `application/dataset_service.py` - edit candidate validation and atomic
  persistence use case.
- `domain/table_editing.py` and `llm.py` - protected table-editing port and
  Gemini structured-output adapter.
- `ui/data_generation.py` and `ui/common.py` - selected-table preview and
  Quick edit form.
- `dataset_repository.py` and `domain/validation.py` - transactional save and
  whole-dataset DDL constraint checks.
- `tests/test_table_editing.py`, `tests/test_llm_table_editor.py`, and
  `tests/test_app_ui.py` - stage-8 regression coverage.
