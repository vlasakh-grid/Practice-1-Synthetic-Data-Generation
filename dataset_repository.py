"""Transactional PostgreSQL storage for the single current generated dataset."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
import json
import re
from typing import Any

try:  # Keep pure validation/schema tests usable before app dependencies are installed.
    from sqlalchemy import Engine, create_engine, text
except ModuleNotFoundError:  # pragma: no cover - exercised only outside the app environment
    Engine = Any  # type: ignore[misc,assignment]
    create_engine = None

    def text(statement: str):
        raise RuntimeError("Dataset persistence requires the SQLAlchemy dependency.")

from domain.draft_generation import DraftDataset, GenerationConfig
from domain.schema import CheckConstraint, Column, ForeignKey, Schema, Table, UniqueConstraint
from domain.validation import ValidationResult, compile_postgres_check, validate_dataset


class DatasetRepositoryError(RuntimeError):
    """Raised when the current dataset cannot be stored or restored."""


class InvalidDatasetError(DatasetRepositoryError):
    """Raised when persistence is requested for a draft that fails validation."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        super().__init__("Dataset failed validation and was not saved.")


class StoredDataset:
    """A PostgreSQL-backed current dataset reconstructed for the Streamlit UI."""

    def __init__(self, schema: Schema, rows_by_table: Mapping[str, tuple[dict[str, Any], ...]], schema_digest: str, saved_at: datetime) -> None:
        self.schema = schema
        self.rows_by_table = rows_by_table
        self.schema_digest = schema_digest
        self.saved_at = saved_at

    def rows_for(self, table_name: str) -> tuple[dict[str, Any], ...]:
        return self.rows_by_table[table_name]


class DatasetRepository:
    """Owns the dedicated generated-data schema and current-dataset metadata."""

    data_schema = "generated_data"
    metadata_schema = "synthetic_app"
    metadata_table = "current_dataset"

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> "DatasetRepository":
        if create_engine is None:
            raise DatasetRepositoryError("Dataset persistence requires the SQLAlchemy dependency.")
        return cls(create_engine(database_url))

    def save(self, schema: Schema, draft: DraftDataset, schema_digest: str) -> datetime:
        """Validate and atomically replace the one persisted current dataset."""

        result = validate_dataset(schema, draft)
        if not result.is_valid:
            raise InvalidDatasetError(result)
        self._require_postgres()
        try:
            with self.engine.begin() as connection:
                self._ensure_metadata(connection)
                connection.execute(text(f"DROP SCHEMA IF EXISTS {_quote(self.data_schema)} CASCADE"))
                connection.execute(text(f"CREATE SCHEMA {_quote(self.data_schema)}"))
                for table in schema.tables:
                    connection.execute(text(_create_table_sql(self.data_schema, table)))
                for table in schema.tables:
                    for foreign_key in table.foreign_keys:
                        connection.execute(text(_add_foreign_key_sql(self.data_schema, table, foreign_key)))
                for table in schema.tables:
                    rows = draft.rows_for(table.name)
                    if rows:
                        connection.execute(text(_insert_sql(self.data_schema, table)), [_persistence_row(table, row) for row in rows])
                saved_at = connection.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()
                connection.execute(
                    text(
                        f"INSERT INTO {_qualified(self.metadata_schema, self.metadata_table)} "
                        "(id, schema_json, schema_digest, saved_at) "
                        "VALUES (1, CAST(:schema_json AS jsonb), :schema_digest, :saved_at) "
                        "ON CONFLICT (id) DO UPDATE SET schema_json = EXCLUDED.schema_json, "
                        "schema_digest = EXCLUDED.schema_digest, saved_at = EXCLUDED.saved_at"
                    ),
                    {
                        "schema_json": json.dumps(asdict(schema)),
                        "schema_digest": schema_digest,
                        "saved_at": saved_at,
                    },
                )
            return saved_at
        except DatasetRepositoryError:
            raise
        except Exception as error:
            raise DatasetRepositoryError(f"Could not save the dataset: {error}") from error

    def load_current(self) -> StoredDataset | None:
        """Return the persisted dataset, if one has been saved previously."""

        self._require_postgres()
        try:
            with self.engine.begin() as connection:
                self._ensure_metadata(connection)
                record = connection.execute(
                    text(f"SELECT schema_json, schema_digest, saved_at FROM {_qualified(self.metadata_schema, self.metadata_table)} WHERE id = 1")
                ).mappings().first()
                if record is None:
                    return None
                schema_json = record["schema_json"]
                if isinstance(schema_json, str):
                    schema_json = json.loads(schema_json)
                schema = schema_from_dict(schema_json)
                rows_by_table: dict[str, tuple[dict[str, Any], ...]] = {}
                for table in schema.tables:
                    order_by = ", ".join(_quote(column) for column in table.primary_key)
                    statement = f"SELECT * FROM {_qualified(self.data_schema, table.name)}"
                    if order_by:
                        statement += f" ORDER BY {order_by}"
                    rows_by_table[table.name] = tuple(dict(row) for row in connection.execute(text(statement)).mappings())
            return StoredDataset(schema, rows_by_table, record["schema_digest"], record["saved_at"])
        except DatasetRepositoryError:
            raise
        except Exception as error:
            raise DatasetRepositoryError(f"Could not restore the current dataset: {error}") from error

    def _ensure_metadata(self, connection) -> None:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_quote(self.metadata_schema)}"))
        connection.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {_qualified(self.metadata_schema, self.metadata_table)} ("
                "id SMALLINT PRIMARY KEY CHECK (id = 1), "
                "schema_json JSONB NOT NULL, "
                "schema_digest TEXT NOT NULL, "
                "saved_at TIMESTAMPTZ NOT NULL)"
            )
        )

    def _require_postgres(self) -> None:
        if self.engine.dialect.name != "postgresql":
            raise DatasetRepositoryError("Dataset persistence requires PostgreSQL.")


def schema_from_dict(value: Mapping[str, Any]) -> Schema:
    """Recreate canonical schema dataclasses from stored JSON metadata."""

    tables: list[Table] = []
    for table_data in value["tables"]:
        columns = [
            Column(
                name=column["name"], raw_type=column["raw_type"], postgres_type=column["postgres_type"],
                nullable=column["nullable"], default=column["default"], is_primary_key=column["is_primary_key"],
                is_unique=column["is_unique"], is_auto_increment=column["is_auto_increment"],
                enum_values=list(column["enum_values"]), checks=[CheckConstraint(**check) for check in column["checks"]],
            )
            for column in table_data["columns"]
        ]
        tables.append(
            Table(
                name=table_data["name"], columns=columns, primary_key=list(table_data["primary_key"]),
                foreign_keys=[ForeignKey(**foreign_key) for foreign_key in table_data["foreign_keys"]],
                unique_constraints=[UniqueConstraint(**unique) for unique in table_data["unique_constraints"]],
                checks=[CheckConstraint(**check) for check in table_data["checks"]],
            )
        )
    return Schema(tables)


def _create_table_sql(schema_name: str, table: Table) -> str:
    definitions = []
    for column in table.columns:
        definition = f"{_quote(column.name)} {_safe_postgres_type(column.postgres_type)}"
        if not column.nullable:
            definition += " NOT NULL"
        definitions.append(definition)
    if table.primary_key:
        definitions.append(f"PRIMARY KEY ({', '.join(_quote(column) for column in table.primary_key)})")
    unique_columns = {tuple(constraint.columns) for constraint in table.unique_constraints}
    unique_columns.update((column.name,) for column in table.columns if column.is_unique)
    for columns in sorted(unique_columns):
        definitions.append(f"UNIQUE ({', '.join(_quote(column) for column in columns)})")
    for check in table.checks:
        definitions.append(f"CHECK ({compile_postgres_check(check.expression, (column.name for column in table.columns))})")
    for column in table.columns:
        for check in column.checks:
            definitions.append(f"CHECK ({compile_postgres_check(check.expression, (item.name for item in table.columns))})")
        if column.enum_values:
            enum_values = ", ".join("'" + value.replace("'", "''") + "'" for value in column.enum_values)
            definitions.append(f"CHECK ({_quote(column.name)} IN ({enum_values}))")
    return f"CREATE TABLE {_qualified(schema_name, table.name)} ({', '.join(definitions)})"


def _add_foreign_key_sql(schema_name: str, table: Table, foreign_key: ForeignKey) -> str:
    columns = ", ".join(_quote(column) for column in foreign_key.columns)
    referenced_columns = ", ".join(_quote(column) for column in foreign_key.referenced_columns)
    constraint = foreign_key.name or f"fk_{table.name}_{'_'.join(foreign_key.columns)}"
    return (
        f"ALTER TABLE {_qualified(schema_name, table.name)} ADD CONSTRAINT {_quote(constraint)} "
        f"FOREIGN KEY ({columns}) REFERENCES {_qualified(schema_name, foreign_key.referenced_table)} ({referenced_columns}) "
        "DEFERRABLE INITIALLY DEFERRED"
    )


def _insert_sql(schema_name: str, table: Table) -> str:
    columns = ", ".join(_quote(column.name) for column in table.columns)
    values = ", ".join(f":{column.name}" for column in table.columns)
    return f"INSERT INTO {_qualified(schema_name, table.name)} ({columns}) VALUES ({values})"


def _persistence_row(table: Table, row: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt JSONB values explicitly when using a textual SQL statement."""

    result = dict(row)
    for column in table.columns:
        if column.postgres_type.upper() == "JSONB" and result.get(column.name) is not None:
            result[column.name] = json.dumps(result[column.name])
    return result


_TYPE_RE = re.compile(r"^(?:SMALLINT|INTEGER|BIGINT|BOOLEAN|TEXT|DATE|TIME|TIMESTAMP|JSONB|VARCHAR\(\d+\)|CHAR\(\d+\)|NUMERIC\(\d+,\s*\d+\)|DECIMAL\(\d+,\s*\d+\)|REAL|DOUBLE PRECISION)$")


def _safe_postgres_type(value: str) -> str:
    normalized = " ".join(value.upper().split())
    if not _TYPE_RE.fullmatch(normalized):
        raise DatasetRepositoryError(f"Unsupported PostgreSQL column type {value!r}.")
    return normalized


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _qualified(schema: str, table: str) -> str:
    return f"{_quote(schema)}.{_quote(table)}"
