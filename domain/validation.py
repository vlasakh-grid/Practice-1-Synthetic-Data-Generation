"""Constraint validation for generated datasets.

The validator deliberately works on the canonical schema rather than a
database connection.  This gives the UI a complete, actionable error list
before a persistence transaction is attempted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Any, Literal

from .draft_generation import DraftDataset
from .schema import CheckConstraint, Schema, Table


@dataclass(frozen=True)
class ValidationError:
    """One failed constraint, with a one-based row number for the UI."""

    table: str
    row: int
    field: str | None
    rule: str
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "Table": self.table,
            "Row": self.row,
            "Field": self.field or "-",
            "Rule": self.rule,
            "Message": self.message,
        }


@dataclass(frozen=True)
class ValidationResult:
    """The complete result of validating a draft."""

    errors: tuple[ValidationError, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors


class CheckExpressionError(ValueError):
    """Raised when a CHECK expression is outside the safe supported subset."""


def validate_dataset(schema: Schema, draft: DraftDataset) -> ValidationResult:
    """Validate all explicit schema constraints against ``draft``.

    ``CHECK`` uses SQL three-valued semantics: a NULL result passes the check.
    Required fields are checked independently, so NULL never hides a NOT NULL
    failure.
    """

    errors: list[ValidationError] = []
    rows_by_table = draft.rows_by_table
    for table in schema.tables:
        rows = rows_by_table.get(table.name, ())
        errors.extend(_validate_required_and_enums(table, rows))
        errors.extend(_validate_primary_key(table, rows))
        errors.extend(_validate_unique(table, rows))
        errors.extend(_validate_checks(table, rows))
        errors.extend(_validate_foreign_keys(table, rows, rows_by_table))
    return ValidationResult(tuple(errors))


def _validate_required_and_enums(table: Table, rows: Iterable[Mapping[str, Any]]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for row_number, row in enumerate(rows, start=1):
        for column in table.columns:
            value = row.get(column.name)
            if not column.nullable and value is None:
                errors.append(_error(table, row_number, column.name, "required", "A value is required."))
            if value is not None and column.enum_values and value not in column.enum_values:
                allowed = ", ".join(repr(item) for item in column.enum_values)
                errors.append(_error(table, row_number, column.name, "enum", f"Value must be one of: {allowed}."))
    return errors


def _validate_primary_key(table: Table, rows: Iterable[Mapping[str, Any]]) -> list[ValidationError]:
    if not table.primary_key:
        return []
    errors: list[ValidationError] = []
    seen: dict[tuple[Any, ...], int] = {}
    for row_number, row in enumerate(rows, start=1):
        values = tuple(row.get(column) for column in table.primary_key)
        if any(value is None for value in values):
            errors.append(_error(table, row_number, _field_for(table.primary_key), "primary_key", "Primary-key values cannot be NULL."))
            continue
        if values in seen:
            errors.append(_error(table, row_number, _field_for(table.primary_key), "primary_key", f"Duplicates row {seen[values]}."))
        else:
            seen[values] = row_number
    return errors


def _validate_unique(table: Table, rows: Iterable[Mapping[str, Any]]) -> list[ValidationError]:
    constraints = [tuple(constraint.columns) for constraint in table.unique_constraints]
    constraints.extend((column.name,) for column in table.columns if column.is_unique)
    errors: list[ValidationError] = []
    for columns in dict.fromkeys(constraints):
        seen: dict[tuple[Any, ...], int] = {}
        for row_number, row in enumerate(rows, start=1):
            values = tuple(row.get(column) for column in columns)
            # PostgreSQL UNIQUE permits multiple NULL-containing tuples.
            if any(value is None for value in values):
                continue
            if values in seen:
                errors.append(_error(table, row_number, _field_for(columns), "unique", f"Duplicates row {seen[values]}."))
            else:
                seen[values] = row_number
    return errors


def _validate_foreign_keys(
    table: Table,
    rows: Iterable[Mapping[str, Any]],
    rows_by_table: Mapping[str, Iterable[Mapping[str, Any]]],
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for foreign_key in table.foreign_keys:
        referenced_rows = rows_by_table.get(foreign_key.referenced_table, ())
        referenced_values = {
            tuple(referenced_row.get(column) for column in foreign_key.referenced_columns)
            for referenced_row in referenced_rows
        }
        for row_number, row in enumerate(rows, start=1):
            values = tuple(row.get(column) for column in foreign_key.columns)
            if any(value is None for value in values):
                continue
            if values not in referenced_values:
                target = f"{foreign_key.referenced_table}({', '.join(foreign_key.referenced_columns)})"
                errors.append(_error(table, row_number, _field_for(foreign_key.columns), "foreign_key", f"No matching value exists in {target}."))
    return errors


def _validate_checks(table: Table, rows: Iterable[Mapping[str, Any]]) -> list[ValidationError]:
    checks: list[tuple[CheckConstraint, str | None]] = [(check, None) for check in table.checks]
    checks.extend((check, column.name) for column in table.columns for check in column.checks)
    errors: list[ValidationError] = []
    for check, field in checks:
        try:
            expression = _Parser(check.expression, {column.name for column in table.columns}).parse()
        except CheckExpressionError as error:
            for row_number, _ in enumerate(rows, start=1):
                errors.append(_error(table, row_number, field, "check", f"Unsupported CHECK expression: {error}"))
            continue
        for row_number, row in enumerate(rows, start=1):
            try:
                result = _evaluate(expression, row)
            except (TypeError, ValueError) as error:
                errors.append(_error(table, row_number, field, "check", f"Could not evaluate CHECK: {error}"))
                continue
            if result is False:
                errors.append(_error(table, row_number, field, "check", f"CHECK failed: {check.expression}"))
    return errors


def _error(table: Table, row: int, field: str | None, rule: str, message: str) -> ValidationError:
    return ValidationError(table.name, row, field, rule, message)


def _field_for(columns: Iterable[str]) -> str | None:
    columns = tuple(columns)
    return columns[0] if len(columns) == 1 else None


Token = tuple[str, str]
_TOKEN_RE = re.compile(
    r"\s*(?:(?P<string>'(?:''|[^'])*')|(?P<number>-?\d+(?:\.\d+)?)|"
    r"(?P<operator><=|>=|<>|!=|=|<|>)|(?P<paren>[(),])|(?P<identifier>[A-Za-z_][A-Za-z0-9_]*))"
)


def _tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    while position < len(source):
        match = _TOKEN_RE.match(source, position)
        if match is None:
            raise CheckExpressionError(f"unexpected token near {source[position:]!r}")
        position = match.end()
        kind = next(name for name, value in match.groupdict().items() if value is not None)
        tokens.append((kind, match.group(kind)))
    return tokens


Ast = tuple[Any, ...]


class _Parser:
    def __init__(self, source: str, columns: set[str]) -> None:
        self.tokens = _tokenize(source)
        self.columns = {column.lower(): column for column in columns}
        self.position = 0

    def parse(self) -> Ast:
        if not self.tokens:
            raise CheckExpressionError("expression is empty")
        expression = self._or()
        if self._peek() is not None:
            raise CheckExpressionError(f"unexpected token {self._peek()[1]!r}")
        return expression

    def _or(self) -> Ast:
        expression = self._and()
        while self._accept_keyword("OR"):
            expression = ("or", expression, self._and())
        return expression

    def _and(self) -> Ast:
        expression = self._not()
        while self._accept_keyword("AND"):
            expression = ("and", expression, self._not())
        return expression

    def _not(self) -> Ast:
        if self._accept_keyword("NOT"):
            return ("not", self._not())
        return self._predicate()

    def _predicate(self) -> Ast:
        if self._accept("paren", "("):
            expression = self._or()
            self._expect("paren", ")")
            return expression
        left = self._value()
        if self._accept_keyword("IS"):
            negated = self._accept_keyword("NOT")
            self._expect_keyword("NULL")
            return ("is_null", left, negated)
        negated_in = self._accept_keyword("NOT")
        if self._accept_keyword("IN"):
            self._expect("paren", "(")
            values = [self._value()]
            while self._accept("paren", ","):
                values.append(self._value())
            self._expect("paren", ")")
            return ("in", left, tuple(values), negated_in)
        if negated_in:
            raise CheckExpressionError("NOT must be followed by IN or NULL")
        operator = self._accept("operator")
        if operator is None:
            raise CheckExpressionError("expected a comparison, IN, or IS NULL")
        return ("compare", operator[1], left, self._value())

    def _value(self) -> Ast:
        token = self._advance()
        if token is None:
            raise CheckExpressionError("expected a value")
        kind, value = token
        if kind == "string":
            return ("literal", value[1:-1].replace("''", "'"))
        if kind == "number":
            return ("literal", Decimal(value))
        if kind == "identifier":
            if value.upper() == "NULL":
                return ("literal", None)
            column = self.columns.get(value.lower())
            if column is None:
                raise CheckExpressionError(f"unknown column {value!r}")
            return ("column", column)
        raise CheckExpressionError(f"expected a value, got {value!r}")

    def _peek(self) -> Token | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _advance(self) -> Token | None:
        token = self._peek()
        if token is not None:
            self.position += 1
        return token

    def _accept(self, kind: str, value: str | None = None) -> Token | None:
        token = self._peek()
        if token is not None and token[0] == kind and (value is None or token[1] == value):
            self.position += 1
            return token
        return None

    def _accept_keyword(self, value: str) -> bool:
        token = self._peek()
        if token is not None and token[0] == "identifier" and token[1].upper() == value:
            self.position += 1
            return True
        return False

    def _expect(self, kind: str, value: str) -> None:
        if self._accept(kind, value) is None:
            raise CheckExpressionError(f"expected {value!r}")

    def _expect_keyword(self, value: str) -> None:
        if not self._accept_keyword(value):
            raise CheckExpressionError(f"expected {value}")


def _evaluate(expression: Ast, row: Mapping[str, Any]) -> Any:
    kind = expression[0]
    if kind == "literal":
        return expression[1]
    if kind == "column":
        return row.get(expression[1])
    if kind == "not":
        value = _evaluate(expression[1], row)
        return None if value is None else not value
    if kind in {"and", "or"}:
        left, right = _evaluate(expression[1], row), _evaluate(expression[2], row)
        if kind == "and":
            if left is False or right is False:
                return False
            return None if left is None or right is None else True
        if left is True or right is True:
            return True
        return None if left is None or right is None else False
    if kind == "is_null":
        value = _evaluate(expression[1], row)
        return (value is not None) if expression[2] else (value is None)
    if kind == "in":
        value = _evaluate(expression[1], row)
        values = [_evaluate(item, row) for item in expression[2]]
        if value is None:
            return None
        matches = any(value == item for item in values if item is not None)
        result: bool | None = True if matches else (None if any(item is None for item in values) else False)
        return None if result is None else (not result if expression[3] else result)
    if kind == "compare":
        left, right = _evaluate(expression[2], row), _evaluate(expression[3], row)
        if left is None or right is None:
            return None
        operator = expression[1]
        return {
            "=": left == right,
            "!=": left != right,
            "<>": left != right,
            "<": left < right,
            "<=": left <= right,
            ">": left > right,
            ">=": left >= right,
        }[operator]
    raise CheckExpressionError(f"unsupported expression node {kind!r}")


def compile_postgres_check(expression: str, columns: Iterable[str]) -> str:
    """Compile a safe CHECK subset to PostgreSQL SQL with quoted identifiers."""

    ast = _Parser(expression, set(columns)).parse()
    return _compile_sql(ast)


def _compile_sql(expression: Ast) -> str:
    kind = expression[0]
    if kind == "literal":
        value = expression[1]
        if value is None:
            return "NULL"
        if isinstance(value, Decimal):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"
    if kind == "column":
        return _quote_identifier(expression[1])
    if kind == "not":
        return f"(NOT {_compile_sql(expression[1])})"
    if kind in {"and", "or"}:
        return f"({_compile_sql(expression[1])} {kind.upper()} {_compile_sql(expression[2])})"
    if kind == "is_null":
        return f"({_compile_sql(expression[1])} IS {'NOT ' if expression[2] else ''}NULL)"
    if kind == "in":
        values = ", ".join(_compile_sql(item) for item in expression[2])
        return f"({_compile_sql(expression[1])} {'NOT ' if expression[3] else ''}IN ({values}))"
    if kind == "compare":
        return f"({_compile_sql(expression[2])} {expression[1]} {_compile_sql(expression[3])})"
    raise CheckExpressionError(f"unsupported expression node {kind!r}")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
