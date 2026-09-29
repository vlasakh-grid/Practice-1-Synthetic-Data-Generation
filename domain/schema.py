"""Canonical, database-neutral representation of an input schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ForeignKey:
    columns: list[str]
    referenced_table: str
    referenced_columns: list[str]
    name: str | None = None
    on_delete: str | None = None
    on_update: str | None = None


@dataclass
class UniqueConstraint:
    columns: list[str]
    name: str | None = None


@dataclass
class CheckConstraint:
    expression: str
    name: str | None = None


@dataclass
class Column:
    name: str
    raw_type: str
    postgres_type: str
    nullable: bool = True
    default: str | None = None
    is_primary_key: bool = False
    is_unique: bool = False
    is_auto_increment: bool = False
    enum_values: list[str] = field(default_factory=list)
    checks: list[CheckConstraint] = field(default_factory=list)


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    unique_constraints: list[UniqueConstraint] = field(default_factory=list)
    checks: list[CheckConstraint] = field(default_factory=list)

    def column(self, name: str) -> Column:
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(f"Table {self.name!r} has no column {name!r}")


@dataclass
class Schema:
    tables: list[Table] = field(default_factory=list)

    def table(self, name: str) -> Table:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(f"Schema has no table {name!r}")

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-compatible form convenient for UI previews and APIs."""
        return asdict(self)
