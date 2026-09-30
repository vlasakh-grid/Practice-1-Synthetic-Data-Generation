"""Create deterministic, foreign-key-aware generation plans from a schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from .schema import ForeignKey, Schema, Table


class DependencyPlanningError(ValueError):
    """Raised when a foreign key references a table outside the parsed schema."""


@dataclass(frozen=True)
class DeferredRelationship:
    """A foreign key populated after its source rows have been created."""

    source_table: str
    source_columns: tuple[str, ...]
    referenced_table: str
    referenced_columns: tuple[str, ...]
    name: str | None = None


@dataclass(frozen=True)
class DependencyCycle:
    """One strongly connected component that needs special generation handling."""

    tables: tuple[str, ...]
    relationships: tuple[DeferredRelationship, ...]
    supported: bool
    status: str


@dataclass(frozen=True)
class GenerationPhase:
    """One ordered stage in a generation plan."""

    kind: Literal["create", "deferred_update"]
    tables: tuple[str, ...] = ()
    relationships: tuple[DeferredRelationship, ...] = ()


@dataclass(frozen=True)
class DependencyPlan:
    """A deterministic plan for creating rows while respecting foreign keys."""

    phases: tuple[GenerationPhase, ...]
    cycles: tuple[DependencyCycle, ...] = ()

    @property
    def is_supported(self) -> bool:
        return all(cycle.supported for cycle in self.cycles)

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-compatible form convenient for UI previews and APIs."""

        return asdict(self) | {"is_supported": self.is_supported}


def plan_generation(schema: Schema) -> DependencyPlan:
    """Build a stable create/deferred-update plan for ``schema``.

    Tables without unresolved dependencies share a create phase.  Foreign keys
    inside a strongly connected component (including self-references) are
    deferred.  A cycle is supported only when every column used by its deferred
    foreign keys is nullable, allowing its seed rows to be created safely.
    """

    tables = {table.name.lower(): table for table in schema.tables}
    if len(tables) != len(schema.tables):
        raise DependencyPlanningError("Schema contains table names that differ only by case")

    graph: dict[str, set[str]] = {name: set() for name in tables}
    foreign_keys: list[tuple[str, ForeignKey]] = []
    for table in schema.tables:
        source = table.name.lower()
        for foreign_key in table.foreign_keys:
            target = foreign_key.referenced_table.lower()
            if target not in tables:
                raise DependencyPlanningError(
                    f"Foreign key on {table.name!r} references missing table {foreign_key.referenced_table!r}"
                )
            graph[target].add(source)
            foreign_keys.append((source, foreign_key))

    components = _strongly_connected_components(graph)
    component_by_table = {
        table_name: component_index
        for component_index, component in enumerate(components)
        for table_name in component
    }
    component_edges: dict[int, set[int]] = {index: set() for index in range(len(components))}
    for parent, children in graph.items():
        for child in children:
            parent_component = component_by_table[parent]
            child_component = component_by_table[child]
            if parent_component != child_component:
                component_edges[parent_component].add(child_component)

    cycles = _cycles(components, component_by_table, foreign_keys, tables)
    cycles_by_component = {
        component_by_table[cycle.tables[0].lower()]: cycle
        for cycle in cycles
    }
    phases: list[GenerationPhase] = []
    for component_group in _topological_groups(component_edges, components):
        phase_tables = tuple(
            sorted(
                (tables[table_name].name for component in component_group for table_name in components[component]),
                key=str.lower,
            )
        )
        phases.append(GenerationPhase(kind="create", tables=phase_tables))

        deferred_relationships = tuple(
            relationship
            for component in component_group
            if (cycle := cycles_by_component.get(component)) is not None and cycle.supported
            for relationship in cycle.relationships
        )
        if deferred_relationships:
            phases.append(GenerationPhase(kind="deferred_update", relationships=deferred_relationships))

    return DependencyPlan(phases=tuple(phases), cycles=tuple(cycles))


def _cycles(
    components: list[tuple[str, ...]],
    component_by_table: dict[str, int],
    foreign_keys: list[tuple[str, ForeignKey]],
    tables: dict[str, Table],
) -> list[DependencyCycle]:
    cycles: list[DependencyCycle] = []
    for component_index, component in enumerate(components):
        internal = [
            (source, foreign_key)
            for source, foreign_key in foreign_keys
            if component_by_table[source] == component_index
            and component_by_table[foreign_key.referenced_table.lower()] == component_index
        ]
        is_self_reference = len(component) == 1 and any(
            source == foreign_key.referenced_table.lower() for source, foreign_key in internal
        )
        if len(component) == 1 and not is_self_reference:
            continue

        relationships = tuple(
            DeferredRelationship(
                source_table=tables[source].name,
                source_columns=tuple(foreign_key.columns),
                referenced_table=tables[foreign_key.referenced_table.lower()].name,
                referenced_columns=tuple(foreign_key.referenced_columns),
                name=foreign_key.name,
            )
            for source, foreign_key in sorted(
                internal,
                key=lambda item: (tables[item[0]].name.lower(), tuple(column.lower() for column in item[1].columns)),
            )
        )
        nullable = all(
            all(tables[source].column(column).nullable for column in foreign_key.columns)
            for source, foreign_key in internal
        )
        cycles.append(
            DependencyCycle(
                tables=tuple(sorted((tables[name].name for name in component), key=str.lower)),
                relationships=relationships,
                supported=nullable,
                status=(
                    "Deferred update after seed-row creation."
                    if nullable
                    else "Cycle is not supported without a special strategy because at least one internal foreign key is NOT NULL."
                ),
            )
        )
    return sorted(cycles, key=lambda cycle: tuple(name.lower() for name in cycle.tables))


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    """Return Tarjan SCCs with deterministic traversal."""

    index = 0
    indices: dict[str, int] = {}
    low_links: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low_links[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for child in sorted(graph[node]):
            if child not in indices:
                visit(child)
                low_links[node] = min(low_links[node], low_links[child])
            elif child in on_stack:
                low_links[node] = min(low_links[node], indices[child])
        if low_links[node] == indices[node]:
            component: list[str] = []
            while True:
                child = stack.pop()
                on_stack.remove(child)
                component.append(child)
                if child == node:
                    break
            components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return components


def _topological_groups(
    edges: dict[int, set[int]], components: list[tuple[str, ...]]
) -> list[tuple[int, ...]]:
    indegree = {component: 0 for component in edges}
    for children in edges.values():
        for child in children:
            indegree[child] += 1

    groups: list[tuple[int, ...]] = []
    ready = {component for component, degree in indegree.items() if degree == 0}
    while ready:
        group = tuple(sorted(ready, key=lambda component: components[component]))
        groups.append(group)
        next_ready: set[int] = set()
        for component in group:
            for child in edges[component]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    next_ready.add(child)
        ready = next_ready
    return groups
