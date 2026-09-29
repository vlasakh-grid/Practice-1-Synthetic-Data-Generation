# Agent Handoff Log

## Completed: DDL parsing

Implemented a DDL parsing layer for the synthetic data application.

### Delivered components

- `domain/schema.py` defines the canonical, database-neutral schema model:
  `Schema`, `Table`, `Column`, `ForeignKey`, `UniqueConstraint`, and
  `CheckConstraint`.
- `domain/ddl_parser.py` exposes `parse_ddl(source: str) -> Schema` and
  `DDLParseError`.
- `domain/__init__.py` exports the public domain API.
- `app.py` accepts `.sql`, `.ddl`, and `.txt` uploads, parses the selected
  file, and displays a table overview plus the parsed schema JSON.
- `tests/test_ddl_parser.py` covers all three supplied schemas and additional
  composite/named constraint and inline foreign-key cases.

### Supported DDL features

- `CREATE TABLE` and `ALTER TABLE ... ADD ... FOREIGN KEY`
- columns, MySQL-like types, and PostgreSQL-compatible normalized types
- `NULL` / `NOT NULL`, `PRIMARY KEY`, `UNIQUE`, `FOREIGN KEY`, `CHECK`,
  `DEFAULT`, `ENUM`, and `AUTO_INCREMENT`
- inline and table-level constraints, including composite primary and unique
  constraints
- foreign-key `ON DELETE` / `ON UPDATE` actions
- MySQL-style line comments and block comments

The parser is intentionally scoped to the MySQL-like DDL in `task/`; it is not
intended to be a complete SQL parser.

## Verification performed

Run from the repository root:

```bash
python3 -m unittest -v
python3 -m compileall -q domain tests app.py
```

Result at implementation time: all 5 tests passed. The parser was also run
against `task/library_mgm_schema.ddl`, producing 9 tables and the expected
foreign-key counts.

## Environment note

`python3` is available. The `python` command is not available. Streamlit was
not installed in the active environment, so the UI was not launched here.
Install project dependencies before manual UI verification:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The DDL upload flow works without `DATABASE_URL`; PostgreSQL remains optional
until data persistence is implemented.

## Next recommended task

Implement the schema dependency model described in
`docs/implementation-plan.md` subtask 4.

Suggested scope:

1. Add a domain module that derives a table dependency graph from
   `Schema.tables[].foreign_keys`.
2. Return a stable generation order for acyclic relationships.
3. Identify self-references and strongly connected components for cycles,
   notably `Employees` and `Departments` in the library schema.
4. Define explicit deferred-generation/update stages for cycles, without
   inventing constraints absent from the source DDL.
5. Add tests for parent-before-child ordering, self-references, and circular
   dependencies.

Keep Streamlit, database, and LLM code out of this domain layer. The dependency
planner should consume the canonical `Schema` model and remain independently
testable.
