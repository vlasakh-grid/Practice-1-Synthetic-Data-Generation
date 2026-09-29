"""Parse the MySQL-like DDL used by the assignment into the canonical model."""

from __future__ import annotations

import re

from .schema import CheckConstraint, Column, ForeignKey, Schema, Table, UniqueConstraint


class DDLParseError(ValueError):
    """Raised when a supported DDL statement is structurally invalid."""


_CREATE_TABLE_RE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>`[^`]+`|\"[^\"]+\"|[\w.]+)\s*\(",
    re.IGNORECASE,
)
_ALTER_FOREIGN_KEY_RE = re.compile(
    r"\bALTER\s+TABLE\s+(?P<table>`[^`]+`|\"[^\"]+\"|[\w.]+)\s+"
    r"ADD\s+(?:CONSTRAINT\s+(?P<name>`[^`]+`|\"[^\"]+\"|\w+)\s+)?"
    r"FOREIGN\s+KEY\s*\((?P<columns>[^)]+)\)\s*REFERENCES\s*"
    r"(?P<target>`[^`]+`|\"[^\"]+\"|[\w.]+)\s*\((?P<target_columns>[^)]+)\)"
    r"(?P<actions>.*?)(?:;|$)",
    re.IGNORECASE | re.DOTALL,
)
_CONSTRAINT_KEYWORDS = re.compile(
    r"\s+(?=(?:NOT\s+NULL|NULL|PRIMARY\s+KEY|UNIQUE|DEFAULT|CHECK|REFERENCES|"
    r"AUTO_INCREMENT|AUTOINCREMENT|COMMENT|COLLATE|CONSTRAINT)\b)",
    re.IGNORECASE,
)


def parse_ddl(source: str) -> Schema:
    """Parse CREATE TABLE and ALTER TABLE ... ADD FOREIGN KEY statements.

    The parser intentionally targets the MySQL-style DDL accepted by this app,
    rather than attempting to be a full SQL parser. Unsupported statements are
    ignored; malformed CREATE TABLE statements raise ``DDLParseError``.
    """
    cleaned_source = _strip_comments(source)
    schema = Schema()

    for match in _CREATE_TABLE_RE.finditer(cleaned_source):
        body_start = match.end() - 1
        body_end = _find_matching_parenthesis(cleaned_source, body_start)
        if body_end is None:
            table_name = _identifier(match.group("name"))
            raise DDLParseError(f"CREATE TABLE {table_name!r} has no closing parenthesis")
        schema.tables.append(_parse_table(_identifier(match.group("name")), cleaned_source[body_start + 1 : body_end]))

    if not schema.tables:
        raise DDLParseError("No CREATE TABLE statements found")

    tables_by_name = {table.name.lower(): table for table in schema.tables}
    for match in _ALTER_FOREIGN_KEY_RE.finditer(cleaned_source):
        table_name = _identifier(match.group("table"))
        table = tables_by_name.get(table_name.lower())
        if table is None:
            continue
        foreign_key = ForeignKey(
            columns=_identifiers(match.group("columns")),
            referenced_table=_identifier(match.group("target")),
            referenced_columns=_identifiers(match.group("target_columns")),
            name=_identifier(match.group("name")) if match.group("name") else None,
            **_referential_actions(match.group("actions")),
        )
        _add_foreign_key(table, foreign_key)

    return schema


def _parse_table(name: str, body: str) -> Table:
    table = Table(name=name)
    for definition in _split_top_level(body):
        if not definition:
            continue
        _parse_definition(table, definition.strip())
    _mark_constraint_columns(table)
    return table


def _parse_definition(table: Table, definition: str) -> None:
    constraint_name, content = _unwrap_named_constraint(definition)
    upper_content = content.upper()

    if upper_content.startswith("PRIMARY KEY"):
        table.primary_key = _constraint_columns(content, "PRIMARY KEY")
        return
    if upper_content.startswith("UNIQUE"):
        table.unique_constraints.append(UniqueConstraint(_constraint_columns(content, "UNIQUE"), constraint_name))
        return
    if upper_content.startswith("FOREIGN KEY"):
        foreign_key = _parse_foreign_key(content, constraint_name)
        _add_foreign_key(table, foreign_key)
        return
    if upper_content.startswith("CHECK"):
        table.checks.append(CheckConstraint(_parenthesized_content(content), constraint_name))
        return

    column = _parse_column(definition)
    if column is not None:
        table.columns.append(column)


def _parse_column(definition: str) -> Column | None:
    match = re.match(r"(?P<name>`[^`]+`|\"[^\"]+\"|\w+)\s+(?P<remainder>.+)$", definition, re.DOTALL)
    if match is None:
        return None
    name = _identifier(match.group("name"))
    pieces = _CONSTRAINT_KEYWORDS.split(match.group("remainder"), maxsplit=1)
    raw_type = pieces[0].strip()
    if not raw_type:
        return None
    constraints = pieces[1] if len(pieces) > 1 else ""
    enum_values = _enum_values(raw_type)
    checks = [CheckConstraint(expression) for expression in _check_expressions(constraints)]
    column = Column(
        name=name,
        raw_type=raw_type,
        postgres_type=_postgres_type(raw_type),
        nullable=not bool(re.search(r"\bNOT\s+NULL\b", constraints, re.IGNORECASE)),
        default=_default_value(constraints),
        is_primary_key=bool(re.search(r"\bPRIMARY\s+KEY\b", constraints, re.IGNORECASE)),
        is_unique=bool(re.search(r"\bUNIQUE\b", constraints, re.IGNORECASE)),
        is_auto_increment=bool(re.search(r"\bAUTO_INCREMENT\b|\bAUTOINCREMENT\b", constraints, re.IGNORECASE)),
        enum_values=enum_values,
        checks=checks,
    )
    reference = _inline_reference(constraints)
    if reference is not None:
        column._inline_foreign_key = reference  # type: ignore[attr-defined]
    return column


def _mark_constraint_columns(table: Table) -> None:
    if not table.primary_key:
        table.primary_key = [column.name for column in table.columns if column.is_primary_key]
    for name in table.primary_key:
        table.column(name).is_primary_key = True
        table.column(name).nullable = False
    for unique in table.unique_constraints:
        if len(unique.columns) == 1:
            table.column(unique.columns[0]).is_unique = True
    for column in table.columns:
        foreign_key = getattr(column, "_inline_foreign_key", None)
        if foreign_key is not None:
            _add_foreign_key(table, foreign_key)
            delattr(column, "_inline_foreign_key")


def _parse_foreign_key(content: str, name: str | None) -> ForeignKey:
    match = re.search(
        r"FOREIGN\s+KEY\s*\((?P<columns>[^)]+)\)\s*REFERENCES\s*"
        r"(?P<table>`[^`]+`|\"[^\"]+\"|[\w.]+)\s*\((?P<target_columns>[^)]+)\)(?P<actions>.*)$",
        content,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        raise DDLParseError(f"Invalid foreign key definition: {content}")
    return ForeignKey(
        columns=_identifiers(match.group("columns")),
        referenced_table=_identifier(match.group("table")),
        referenced_columns=_identifiers(match.group("target_columns")),
        name=name,
        **_referential_actions(match.group("actions")),
    )


def _inline_reference(constraints: str) -> ForeignKey | None:
    match = re.search(
        r"\bREFERENCES\s+(?P<table>`[^`]+`|\"[^\"]+\"|[\w.]+)\s*\((?P<columns>[^)]+)\)(?P<actions>.*)$",
        constraints,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None
    return ForeignKey(
        columns=[],
        referenced_table=_identifier(match.group("table")),
        referenced_columns=_identifiers(match.group("columns")),
        **_referential_actions(match.group("actions")),
    )


def _add_foreign_key(table: Table, foreign_key: ForeignKey) -> None:
    if not foreign_key.columns:
        # Inline REFERENCES is stored on its source column until this point.
        source_column = next(
            (column for column in table.columns if getattr(column, "_inline_foreign_key", None) is foreign_key), None
        )
        if source_column is not None:
            foreign_key.columns = [source_column.name]
    if foreign_key.columns and foreign_key not in table.foreign_keys:
        table.foreign_keys.append(foreign_key)


def _constraint_columns(content: str, keyword: str) -> list[str]:
    match = re.search(rf"{keyword}\s*\((?P<columns>[^)]+)\)", content, re.IGNORECASE)
    if match is None:
        raise DDLParseError(f"Invalid {keyword} constraint: {content}")
    return _identifiers(match.group("columns"))


def _unwrap_named_constraint(definition: str) -> tuple[str | None, str]:
    match = re.match(r"CONSTRAINT\s+(?P<name>`[^`]+`|\"[^\"]+\"|\w+)\s+(?P<content>.+)$", definition, re.IGNORECASE | re.DOTALL)
    if match is None:
        return None, definition
    return _identifier(match.group("name")), match.group("content").strip()


def _postgres_type(raw_type: str) -> str:
    normalized = re.sub(r"\s+", " ", raw_type.strip()).upper()
    if normalized.startswith("ENUM"):
        return "TEXT"
    mappings = {
        "INT": "INTEGER",
        "INTEGER": "INTEGER",
        "TINYINT": "SMALLINT",
        "SMALLINT": "SMALLINT",
        "MEDIUMINT": "INTEGER",
        "BIGINT": "BIGINT",
        "DATETIME": "TIMESTAMP",
        "BOOL": "BOOLEAN",
        "BOOLEAN": "BOOLEAN",
        "TEXT": "TEXT",
        "DATE": "DATE",
        "TIME": "TIME",
        "TIMESTAMP": "TIMESTAMP",
        "JSON": "JSONB",
    }
    base = re.match(r"[A-Z]+", normalized)
    if base and base.group(0) in mappings:
        mapped = mappings[base.group(0)]
        suffix = normalized[len(base.group(0)) :]
        return mapped + suffix if mapped in {"VARCHAR", "CHAR", "NUMERIC", "DECIMAL"} else mapped
    return normalized


def _enum_values(raw_type: str) -> list[str]:
    match = re.match(r"ENUM\s*\((?P<values>.*)\)$", raw_type.strip(), re.IGNORECASE | re.DOTALL)
    if match is None:
        return []
    return _quoted_values(match.group("values"))


def _default_value(constraints: str) -> str | None:
    match = re.search(
        r"\bDEFAULT\s+(?P<value>'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|\([^)]*\)|[^\s,]+)",
        constraints,
        re.IGNORECASE,
    )
    return match.group("value") if match else None


def _check_expressions(constraints: str) -> list[str]:
    expressions: list[str] = []
    for match in re.finditer(r"\bCHECK\s*\(", constraints, re.IGNORECASE):
        start = match.end() - 1
        end = _find_matching_parenthesis(constraints, start)
        if end is not None:
            expressions.append(constraints[start + 1 : end].strip())
    return expressions


def _parenthesized_content(content: str) -> str:
    start = content.find("(")
    end = _find_matching_parenthesis(content, start)
    if start == -1 or end is None:
        raise DDLParseError(f"Invalid CHECK constraint: {content}")
    return content[start + 1 : end].strip()


def _referential_actions(content: str) -> dict[str, str | None]:
    actions: dict[str, str | None] = {"on_delete": None, "on_update": None}
    for action, value in re.findall(r"\bON\s+(DELETE|UPDATE)\s+(CASCADE|RESTRICT|SET\s+NULL|SET\s+DEFAULT|NO\s+ACTION)", content, re.IGNORECASE):
        actions[f"on_{action.lower()}"] = re.sub(r"\s+", " ", value.upper())
    return actions


def _identifiers(value: str) -> list[str]:
    return [_identifier(part.strip()) for part in value.split(",")]


def _identifier(value: str) -> str:
    return value.strip().strip("`\"")


def _quoted_values(value: str) -> list[str]:
    return [match.group(1).replace("''", "'") for match in re.finditer(r"'((?:''|[^'])*)'", value)]


def _split_top_level(value: str) -> list[str]:
    parts: list[str] = []
    start = depth = 0
    quote: str | None = None
    index = 0
    while index < len(value):
        character = value[index]
        if quote:
            if character == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in "'\"`":
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
        index += 1
    parts.append(value[start:].strip())
    return parts


def _find_matching_parenthesis(value: str, start: int) -> int | None:
    depth = 0
    quote: str | None = None
    index = start
    while index < len(value):
        character = value[index]
        if quote:
            if character == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in "'\"`":
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", source)
