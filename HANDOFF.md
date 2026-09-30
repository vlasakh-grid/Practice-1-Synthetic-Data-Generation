# Current Status

## Completed

- Completed stage 4: dependency planning and integration readiness.
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

## Verification

- Command: `python3 -m unittest -v`
- Result: all 12 tests passed, covering parser behavior, all supplied-schema
  generation orders, the library cycle, self-references, required cycles, and
  secret-safe readiness states.
- Command: `python3 -m compileall -q domain tests app.py integration_readiness.py`
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

## Known Limitations

- The parser targets the MySQL-like DDL used in `task/`; it is not a complete
  SQL parser.
- Streamlit is a project dependency, not a guaranteed global command. Use the
  documented `.venv` startup path for host-local UI checks.
- Readiness confirms configuration only; it does not validate Vertex ADC,
  Gemini access, Langfuse connectivity, or send traces.
- Dataset generation, validation, and PostgreSQL persistence are not
  implemented yet. Cycles with internal `NOT NULL` foreign keys remain blocked.

## Next Steps

1. Implement stage 5 draft generation using the dependency-plan phases.
2. Generate nullable-cycle seed rows first, then fill the listed deferred FK
   relationships after referenced primary keys exist.
3. Use Gemini structured output for semantic values and show per-table
   in-memory draft previews with streaming progress.

## Important Files

- `domain/dependency_planner.py` - public FK planning model and algorithm.
- `integration_readiness.py` - local, secret-safe configuration checks.
- `app.py` - DDL upload, `.env` loading, plan, and readiness rendering.
- `tests/test_dependency_planner.py` - dependency-plan coverage.
- `tests/test_integration_readiness.py` - readiness privacy coverage.
- `docs/implementation-plan.md` - completed stage tracking.
