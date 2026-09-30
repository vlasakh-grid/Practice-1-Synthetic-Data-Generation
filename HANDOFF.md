# Current Status

## Completed

- Stage 6 is complete: drafts are validated before an explicit `Save dataset`
  action, and the one current dataset persists in PostgreSQL across Streamlit
  restarts.
- Public interfaces added: `validate_dataset(schema, draft) ->
  ValidationResult`, `ValidationError`, `DatasetRepository.save(...)`, and
  `DatasetRepository.load_current()`.
- Validation reports table, one-based row, optional field, rule, and message
  for PK, FK, required, unique, enum, and supported CHECK failures. Unsupported
  CHECK syntax blocks persistence safely.
- PostgreSQL uses `generated_data` for restored user tables and
  `synthetic_app.current_dataset` for canonical schema metadata, digest, and
  saved time. Replacing a dataset is one transaction.
- The UI restores the saved dataset without a DDL upload and includes a
  non-persisting invalid-draft demo for manual error presentation checks.

## Verification

- Command: `python3 -m unittest -v`
- Result: 24 tests passed and one SQLAlchemy-dependent repository test was
  skipped because the system Python lacks app dependencies. Coverage includes
  validation, stored-schema reconstruction, and invalid-write prevention.
- Command: `.venv/bin/python -m unittest -v && .venv/bin/python -m compileall -q domain tests app.py dataset_repository.py integration_readiness.py llm.py`
- Result: 25 tests passed and compilation completed successfully with app dependencies installed.
- Command: `docker compose config --quiet`
- Result: configuration validated. PostgreSQL persistence was not run because Docker Desktop was unavailable.
- Manual scenario to run after Docker Desktop starts: generate and save each
  supplied schema, restart Streamlit, verify the restored preview, then select
  `Load invalid validation demo` and verify the error table and disabled save
  action. Preserve prior generation-cycle checks for the library schema.
- Manual result: local Streamlit socket startup is blocked by the execution
  sandbox (`PermissionError`), so the browser scenario remains unverified.

## Known Limitations

- PostgreSQL transaction and browser persistence flows require Docker Desktop;
  they were not executable in this environment.
- CHECK validation supports the safe subset: AND/OR/NOT, comparisons, IN,
  IS [NOT] NULL, and parentheses. Other parsed SQL checks are displayed as
  validation errors and cannot be saved.
- Vertex AI and Langfuse credentials remain required for real semantic
  generation; unsupported cycles with internal NOT NULL FKs remain blocked.

## Next Steps

1. Implement stage 7's target Data Generation workflow layout while preserving
   validation, save, and restore behavior.
2. Use `DatasetRepository` for subsequent atomic dataset edits and exports.

## Important Files

- `domain/validation.py` - safe constraint validation and CHECK compiler.
- `dataset_repository.py` - PostgreSQL transaction and schema restoration.
- `app.py` - validation, save, invalid-demo, and restored-preview UI.
- `tests/test_validation.py` and `tests/test_dataset_repository.py` - stage 6 coverage.
- `docs/implementation-plan.md` - stage tracking.
