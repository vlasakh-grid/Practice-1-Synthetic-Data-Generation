"""Streamlit entrypoint and composition root for the data assistant."""

import streamlit as st

from application.bootstrap import build_runtime
from ui.common import hide_streamlit_deploy_button, render_sidebar
from ui.data_generation import render_data_generation
from ui.talk_to_data import render_talk_to_your_data


def main() -> None:
    """Assemble the runtime and route the selected Streamlit page."""

    st.set_page_config(
        page_title="Data Assistant",
        page_icon="🗃️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    hide_streamlit_deploy_button()
    runtime = build_runtime()
    page = render_sidebar()

    if page == "Data Generation":
        render_data_generation(runtime)
    else:
        render_talk_to_your_data(runtime)


if __name__ == "__main__":
    main()
