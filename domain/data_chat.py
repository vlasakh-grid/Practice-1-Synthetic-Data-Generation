"""Typed, bounded read-only analytics operations for the data chat.

The model never supplies SQL.  It can only request one of the dataclasses in
this module, which are validated against the saved canonical schema before an
infrastructure adapter can build a query.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from domain.schema import Schema, Table


MAX_QUESTION_LENGTH = 1_000
MAX_TOOL_CALLS = 4
MAX_ROW_LIMIT = 50
MAX_GROUP_LIMIT = 50
MAX_FILTERS = 10
DATABASE_TIMEOUT_MS = 3_000


class ChatSafetyError(ValueError):
    """Raised for a request that should be refused before model or database use."""


class AnalyticsOperationError(ValueError):
    """Raised when a proposed analytics tool call is outside the allowlist."""


@dataclass(frozen=True)
class EqualityFilter:
    column: str
    value: str | int | float | bool | None


@dataclass(frozen=True)
class SchemaLookup:
    table_name: str | None = None


@dataclass(frozen=True)
class Aggregate:
    table_name: str
    metric: str
    column: str | None = None
    group_by: str | None = None
    filters: tuple[EqualityFilter, ...] = ()


@dataclass(frozen=True)
class RowRetrieval:
    table_name: str
    columns: tuple[str, ...]
    filters: tuple[EqualityFilter, ...] = ()
    order_by: str | None = None
    descending: bool = False
    limit: int = 25


AnalyticsOperation = SchemaLookup | Aggregate | RowRetrieval


_DANGEROUS_SQL = re.compile(
    r"\b(?:alter|create|delete|drop|grant|insert|revoke|truncate|update|vacuum)\b",
    re.IGNORECASE,
)
_RAW_SQL = re.compile(r"\bselect\b[\s\S]*\bfrom\b", re.IGNORECASE)
_DATA_CHANGE_REQUEST = re.compile(
    r"\b(?:add|cancel|change|delete|decrease|increase|modify|remove|rename|replace|set|update)\b"
    r"[\s\S]{0,80}\b(?:data|dataset|item|order|record|row|table|value)\b",
    re.IGNORECASE,
)
_SECRET_REQUEST = re.compile(
    r"\b(?:api[ _-]?key|credential|connection[ _-]?string|database[ _-]?url|env(?:ironment)?|password|secret|token)\b",
    re.IGNORECASE,
)
_OVERSIZED_REQUEST = re.compile(r"\b(?:all rows|entire dataset|full dataset|every record|export)\b", re.IGNORECASE)
_NUMERIC_TYPE = re.compile(r"^(?:SMALLINT|INTEGER|BIGINT|NUMERIC|DECIMAL|REAL|DOUBLE)")


def validate_question(question: str) -> str:
    """Return a safe question or reject it without contacting Gemini or PostgreSQL."""

    normalized = question.strip()
    if not normalized:
        raise ChatSafetyError("Enter an analytics question before sending it.")
    if len(normalized) > MAX_QUESTION_LENGTH:
        raise ChatSafetyError("Questions are limited to 1,000 characters. Please make this request more specific.")
    if _SECRET_REQUEST.search(normalized):
        raise ChatSafetyError("Credentials and configuration are not available in chat. Ask about the saved dataset instead.")
    if _DANGEROUS_SQL.search(normalized) or _RAW_SQL.search(normalized) or _DATA_CHANGE_REQUEST.search(normalized):
        raise ChatSafetyError("Chat can only analyze data; it cannot run SQL or change the dataset.")
    if _OVERSIZED_REQUEST.search(normalized):
        raise ChatSafetyError("Chat returns bounded results. Ask for a count, summary, or up to 50 specific rows instead.")
    return normalized


def parse_operation(name: str, arguments: Mapping[str, Any], schema: Schema) -> AnalyticsOperation:
    """Validate a Gemini function-call payload and construct a safe operation."""

    if name == "lookup_schema":
        _reject_unknown_keys(arguments, {"table_name"})
        table_name = arguments.get("table_name")
        if table_name is not None:
            _table(schema, _string(table_name, "table_name"))
        return SchemaLookup(table_name=table_name)
    if name == "aggregate":
        _reject_unknown_keys(arguments, {"table_name", "metric", "column", "group_by", "filters"})
        table = _table(schema, _string(arguments.get("table_name"), "table_name"))
        metric = _string(arguments.get("metric"), "metric").lower()
        if metric not in {"count", "sum", "avg", "min", "max"}:
            raise AnalyticsOperationError("Only count, sum, avg, min, and max aggregates are allowed.")
        column = _optional_column(table, arguments.get("column"), "column")
        if metric == "count":
            if column is not None:
                raise AnalyticsOperationError("Count must not specify a column.")
        elif column is None:
            raise AnalyticsOperationError(f"{metric} requires a valid column.")
        elif metric in {"sum", "avg"} and not _is_numeric(table, column):
            raise AnalyticsOperationError(f"{metric} requires a numeric column.")
        group_by = _optional_column(table, arguments.get("group_by"), "group_by")
        return Aggregate(table.name, metric, column, group_by, _filters(table, arguments.get("filters")))
    if name == "retrieve_rows":
        _reject_unknown_keys(arguments, {"table_name", "columns", "filters", "order_by", "descending", "limit"})
        table = _table(schema, _string(arguments.get("table_name"), "table_name"))
        provided_columns = arguments.get("columns")
        if provided_columns is None:
            columns = tuple(column.name for column in table.columns)
        elif isinstance(provided_columns, list) and provided_columns:
            columns = tuple(_column(table, _string(value, "columns")) for value in provided_columns)
        else:
            raise AnalyticsOperationError("columns must be a non-empty list when supplied.")
        if len(set(columns)) != len(columns):
            raise AnalyticsOperationError("columns must not contain duplicates.")
        order_by = _optional_column(table, arguments.get("order_by"), "order_by")
        descending = arguments.get("descending", False)
        if not isinstance(descending, bool):
            raise AnalyticsOperationError("descending must be true or false.")
        limit = arguments.get("limit", 25)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_ROW_LIMIT:
            raise AnalyticsOperationError(f"limit must be between 1 and {MAX_ROW_LIMIT}.")
        return RowRetrieval(table.name, columns, _filters(table, arguments.get("filters")), order_by, descending, limit)
    raise AnalyticsOperationError("Only lookup_schema, aggregate, and retrieve_rows are available.")


def schema_summary(schema: Schema, table_name: str | None = None) -> dict[str, Any]:
    """Return safe schema metadata for a tool response or model context."""

    tables = schema.tables if table_name is None else [_table(schema, table_name)]
    return {
        "tables": [
            {
                "name": table.name,
                "columns": [
                    {"name": column.name, "type": column.postgres_type, "nullable": column.nullable}
                    for column in table.columns
                ],
                "primary_key": table.primary_key,
            }
            for table in tables
        ]
    }


def _table(schema: Schema, name: str) -> Table:
    try:
        return schema.table(name)
    except KeyError as error:
        raise AnalyticsOperationError(f"Unknown table {name!r}.") from error


def _column(table: Table, name: str) -> str:
    if name not in {column.name for column in table.columns}:
        raise AnalyticsOperationError(f"Unknown column {name!r} for table {table.name!r}.")
    return name


def _optional_column(table: Table, value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _column(table, _string(value, field))


def _filters(table: Table, value: Any) -> tuple[EqualityFilter, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_FILTERS:
        raise AnalyticsOperationError(f"filters must contain at most {MAX_FILTERS} equality filters.")
    filters: list[EqualityFilter] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise AnalyticsOperationError("Each filter must be an object with column and value.")
        _reject_unknown_keys(item, {"column", "value"})
        column = _column(table, _string(item.get("column"), "filter column"))
        raw_value = item.get("value")
        if raw_value is not None and (not isinstance(raw_value, (str, int, float, bool)) or isinstance(raw_value, complex)):
            raise AnalyticsOperationError("Filter values must be strings, numbers, booleans, or null.")
        if column in seen:
            raise AnalyticsOperationError("Only one equality filter per column is allowed.")
        seen.add(column)
        filters.append(EqualityFilter(column, raw_value))
    return tuple(filters)


def _is_numeric(table: Table, column_name: str) -> bool:
    column = next(column for column in table.columns if column.name == column_name)
    return bool(_NUMERIC_TYPE.match(column.postgres_type.upper()))


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalyticsOperationError(f"{field} must be a non-empty string.")
    return value.strip()


def _reject_unknown_keys(value: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise AnalyticsOperationError("Unsupported tool arguments: " + ", ".join(sorted(unknown)))
