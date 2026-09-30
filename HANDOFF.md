# Current Status

## Completed

- Stage 9 is complete: a selected persisted table downloads as a UTF-8 CSV
  with DDL-ordered headers, and the complete persisted dataset downloads as
  `current-dataset.zip` containing one CSV per table in schema order.
- `application.dataset_export.export_table_csv(dataset, table_name)` and
  `export_dataset_zip(dataset)` are in-memory, read-only public export
  interfaces. NULL values become empty CSV cells; the ZIP contains no schema
  or metadata files.
- Export controls appear only for the saved preview, never for an in-memory
  draft, and reuse the runtime's restored `StoredDataset` without a database
  query or mutation.
- Stage 8 quick edits remain atomic and validate the complete candidate
  dataset; the Stage 7 generation, validation, persistence, and navigation
  workflows remain available.

## Verification

- Command: `.venv/bin/python -m unittest -v`
- Result: 36 tests passed, including CSV/ZIP content and order, NULL handling,
  saved-preview download controls, draft export exclusion, quick-edit, and
  persistence regressions.
- Command: `.venv/bin/python -m compileall -q app.py application ui domain tests dataset_repository.py integration_readiness.py llm.py`
- Result: completed successfully.
- Command: `docker compose config --quiet`
- Result: configuration validated.
- Command: `git diff --check`
- Result: completed successfully.
- Manual scenario to run with Docker Desktop: save a generated multi-table
  dataset, select a table, download its CSV and download the complete ZIP.
  Unpack the ZIP and compare every file name, header, and row with the UI;
  restart Streamlit and repeat with the restored dataset. Also preserve the
  Stage 8 valid/invalid quick-edit scenario and the Stage 7
  DDL-upload-to-saved-preview, invalid-draft, and library-cycle scenarios.

## Known Limitations

- PostgreSQL transaction, browser persistence, and browser download flows
  require Docker Desktop; end-to-end browser downloads were not verified in
  this sandbox.
- Quick edits intentionally preserve row count, primary keys, and foreign keys;
  they do not add/delete records or relink existing relationships.
- CHECK validation supports only the existing safe subset, and Vertex AI plus
  Langfuse credentials remain required for real generation and editing; exports
  do not require either integration.

## Next Steps

1. Implement stage 10 session-only, read-only Talk to your data chat.
2. Implement stage 11 chat hardening and the end-to-end demo guide.

## Important Files

- `application/dataset_export.py` - public CSV and ZIP serialization
  functions for `StoredDataset`.
- `ui/data_generation.py` - saved-preview download controls alongside quick
  editing.
- `tests/test_dataset_export.py` and `tests/test_app_ui.py` - export format,
  archive, and UI regression coverage.
- `application/dataset_service.py`, `dataset_repository.py`, and
  `ui/talk_to_data.py` - persistence boundary and the next Stage 10 entry
  points.
