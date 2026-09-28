"""Temporary Streamlit entry point used to validate the local environment."""

import os

import streamlit as st
from sqlalchemy import create_engine, text


st.set_page_config(page_title="Data Assistant", page_icon="🗃️", layout="wide")
st.title("Data Assistant")
st.caption("Environment setup is complete. Data-generation features will be added next.")

database_url = os.getenv("DATABASE_URL")
if not database_url:
    st.error("DATABASE_URL is not configured.")
    st.stop()

try:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
except Exception as error:
    st.error("PostgreSQL is unavailable.")
    st.exception(error)
else:
    st.success("Connected to PostgreSQL container.")
