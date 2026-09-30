"""Streamlit entry point for DDL upload and synthetic data workflows."""

import os

from dotenv import load_dotenv
import streamlit as st
from sqlalchemy import create_engine, text

from domain.dependency_planner import plan_generation
from domain.ddl_parser import DDLParseError, parse_ddl
from integration_readiness import inspect_integration_readiness

load_dotenv()


def _render_generation_plan(schema) -> None:
    """Render the deterministic plan without coupling the planner to Streamlit."""

    plan = plan_generation(schema)
    st.subheader("Generation plan")
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


def _render_integration_readiness() -> None:
    """Render local configuration status without contacting Gemini or Langfuse."""

    st.subheader("Integration readiness")
    st.caption("Configuration only — no network requests are made and secrets are never displayed.")
    for check in inspect_integration_readiness():
        details = " · ".join(f"{label}: {value}" for label, value in check.details.items())
        if check.configured:
            st.success(f"{check.name}: configured — {details}")
        else:
            st.warning(f"{check.name}: missing {', '.join(check.missing_variables)} — {details}")


st.set_page_config(page_title="Data Assistant", page_icon="🗃️", layout="wide")
st.title("Data Assistant")
st.caption("Upload a schema to inspect the constraints that will guide data generation.")

uploaded_ddl = st.file_uploader(
    "DDL schema",
    type=["sql", "ddl", "txt"],
    help="MySQL-like CREATE TABLE statements are supported.",
)
if uploaded_ddl is not None:
    try:
        schema = parse_ddl(uploaded_ddl.getvalue().decode("utf-8"))
    except UnicodeDecodeError:
        st.error("The uploaded file must be UTF-8 encoded text.")
    except DDLParseError as error:
        st.error(f"The DDL could not be parsed: {error}")
    else:
        st.success(f"Parsed {len(schema.tables)} tables.")
        overview = [
            {
                "Table": table.name,
                "Columns": len(table.columns),
                "Primary key": ", ".join(table.primary_key) or "-",
                "Foreign keys": len(table.foreign_keys),
            }
            for table in schema.tables
        ]
        st.dataframe(overview, hide_index=True, use_container_width=True)
        with st.expander("Parsed schema details"):
            st.json(schema.as_dict())
        _render_generation_plan(schema)
        _render_integration_readiness()

database_url = os.getenv("DATABASE_URL")
if not database_url:
    st.info("PostgreSQL is not configured yet. DDL parsing is available without it.")
else:
    try:
        engine = create_engine(database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        st.warning(f"PostgreSQL is unavailable: {error}")
    else:
        st.success("Connected to PostgreSQL container.")
