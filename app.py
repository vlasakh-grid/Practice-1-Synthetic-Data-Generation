"""Streamlit entry point for DDL upload and synthetic data workflows."""

import os

import streamlit as st
from sqlalchemy import create_engine, text

from domain.ddl_parser import DDLParseError, parse_ddl


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
