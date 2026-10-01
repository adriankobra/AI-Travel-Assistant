"""Temporary Phase 2 UI for checking local Groq configuration."""

import streamlit as st

from app.ai.groq_client import GroqClientError, test_groq_connection


def render_groq_connection_test() -> None:
    """Render an opt-in diagnostic; no API request occurs until the button is pressed."""
    with st.expander("Developer: test Groq connection"):
        st.caption("This temporary Phase 2 check sends one small structured request to Groq.")
        if st.button("Test Groq connection", key="test-groq-connection"):
            with st.spinner("Contacting Groq..."):
                try:
                    result = test_groq_connection()
                except GroqClientError as error:
                    st.error(str(error))
                else:
                    st.success("Groq connection successful.")
                    st.json(result)
