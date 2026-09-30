"""Optional schema and integration diagnostics for the generation page."""

from __future__ import annotations

import streamlit as st

from domain.dependency_planner import plan_generation
from integration_readiness import inspect_integration_readiness


def render_generation_plan(schema) -> None:
    """Render the deterministic dependency plan."""

    plan = plan_generation(schema)
    if plan.is_supported:
        st.success("The schema has a safe generation plan.")
    else:
        st.error("This schema contains a cycle that needs a special generation strategy.")

    for number, phase in enumerate(plan.phases, start=1):
        if phase.kind == "create":
            st.markdown(f"**Phase {number}: create seed rows**")
            st.write(", ".join(phase.tables))
        else:
            st.markdown(f"**Phase {number}: populate deferred foreign keys**")
            st.dataframe(
                [
                    {
                        "Source table": relationship.source_table,
                        "Source columns": ", ".join(relationship.source_columns),
                        "Referenced table": relationship.referenced_table,
                        "Referenced columns": ", ".join(relationship.referenced_columns),
                    }
                    for relationship in phase.relationships
                ],
                hide_index=True,
                use_container_width=True,
            )

    if plan.cycles:
        st.markdown("**Detected cycles**")
        for cycle in plan.cycles:
            tables = " → ".join((*cycle.tables, cycle.tables[0]))
            if cycle.supported:
                st.info(f"{tables}: {cycle.status}")
            else:
                st.warning(f"{tables}: {cycle.status}")


def render_integration_readiness() -> None:
    """Render configuration status without contacting Gemini or Langfuse."""

    st.caption("Configuration only — no network requests are made and secrets are never displayed.")
    for check in inspect_integration_readiness():
        details = " · ".join(f"{label}: {value}" for label, value in check.details.items())
        if check.configured:
            st.success(f"{check.name}: configured — {details}")
        else:
            st.warning(f"{check.name}: missing {', '.join(check.missing_variables)} — {details}")


def render_schema_details(schema) -> None:
    """Keep diagnostics available without interrupting the main workflow."""

    overview = [
        {
            "Table": table.name,
            "Columns": len(table.columns),
            "Primary key": ", ".join(table.primary_key) or "-",
            "Foreign keys": len(table.foreign_keys),
        }
        for table in schema.tables
    ]
    with st.expander("Schema details"):
        st.dataframe(overview, hide_index=True, use_container_width=True)
        st.json(schema.as_dict())
    with st.expander("Generation plan"):
        render_generation_plan(schema)
    with st.expander("Integration readiness"):
        render_integration_readiness()
