"""Streamlit entry point for the AI Travel Planner MVP."""

from pathlib import Path
import sys

import streamlit as st

# Make ``app`` importable when Streamlit runs ``src/main.py`` directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.ui.questionnaire import render_questionnaire
from app.ui.connection_test import render_groq_connection_test
from app.ui.results import render_results


st.set_page_config(
    page_title="AI Travel Planner",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def apply_styles() -> None:
    """Apply a high-contrast, Streamlit-safe travel-app visual system."""
    st.markdown(
        """
        <style>
          :root { --ink: #102a43; --muted: #526b7a; --blue: #087ea4; --cyan: #0ea5c6;
            --surface: #ffffff; --line: #d9e7ee; --soft-blue: #e8f8fc; }
          .stApp { background: #f4f8fb; color: var(--ink); }
          .main .block-container { max-width: 920px; padding: 2.25rem 1.25rem 3.5rem; }
          h1, h2, h3, p, label, .stMarkdown, [data-testid="stWidgetLabel"] p,
          [data-testid="stCaptionContainer"], [data-testid="stText"] { color: var(--ink) !important; }
          h1 { font-size: 2.1rem !important; font-weight: 750 !important; letter-spacing: -.04em; }
          h2 { font-size: 1.7rem !important; font-weight: 700 !important; letter-spacing: -.025em; }
          small, .stCaption { color: var(--muted) !important; }
          .app-brand { text-align: center; margin: .3rem 0 1.35rem; }
          .app-brand .eyebrow { color: var(--blue); font-weight: 800; font-size: .8rem;
            letter-spacing: .14em; }
          .app-brand p { color: var(--muted) !important; margin: .2rem 0 0; }
          .hero { text-align: center; padding: 4.5rem 1rem 2.5rem; }
          .hero h1 { margin-bottom: .4rem; }
          .hero p { color: var(--muted) !important; font-size: 1.1rem; }
          .question-card { background: var(--surface); border: 1px solid var(--line); border-radius: 24px;
            padding: clamp(1.35rem, 4vw, 2.6rem); box-shadow: 0 14px 36px rgba(25, 69, 88, .09);
            margin: 1.25rem auto 1.5rem; }
          .question-icon { font-size: 2.3rem; text-align: center; margin-bottom: .4rem; }
          .question-intro { color: var(--muted) !important; text-align: center; margin: -.3rem 0 1.5rem; }
          .summary-card { background: var(--surface); border-radius: 16px; padding: 1rem 1.2rem;
            border: 1px solid var(--line); min-height: 115px; color: var(--ink) !important; }
          .travel-progress-label { color: var(--muted) !important; font-size: .86rem; font-weight: 700;
            margin: 0 0 .45rem; }
          .travel-progress-track { height: 7px; background: #d9eaf1 !important; border-radius: 999px; overflow: hidden;
            margin-bottom: 1.25rem; }
          .travel-progress-fill { display: block; height: 100%; background: var(--cyan) !important; border-radius: inherit; }
          /* Streamlit can apply theme styles after injected CSS. These rules deliberately
             force readable contrast for every button and its inner label. */
          .stButton button { min-height: 58px; border-radius: 14px !important; font-weight: 700 !important;
            padding: .7rem 1rem !important; transition: transform .15s ease, box-shadow .15s ease !important; }
          .stButton button[kind="secondary"], .stButton button[kind="secondary"] * {
            background: #ffffff !important; color: var(--ink) !important; border-color: #bfd3dd !important; }
          .stButton button[kind="primary"], .stButton button[kind="primary"] * {
            background: var(--blue) !important; color: #ffffff !important; border-color: var(--blue) !important; }
          .stButton button:hover { transform: translateY(-1px); box-shadow: 0 7px 16px rgba(25, 69, 88, .13) !important; }
          .st-key-choice-cards [data-testid="stButton"] button {
            min-height: 112px; width: 100%; padding: 1rem; border: 1px solid var(--line);
            border-radius: 16px; background: #fff; color: var(--ink) !important; font-size: 1rem;
            font-weight: 650; white-space: pre-wrap; box-shadow: 0 3px 10px rgba(19, 58, 76, .04);
            transition: transform .15s ease, border-color .15s ease, background .15s ease; }
          .st-key-choice-cards [data-testid="stButton"] button:hover {
            border-color: var(--cyan); background: var(--soft-blue); transform: translateY(-2px); }
          .st-key-choice-cards [data-testid="stButton"] button[kind="primary"] {
            background: var(--soft-blue); border: 2px solid var(--cyan); color: #07556e !important;
            box-shadow: 0 8px 18px rgba(14, 165, 198, .16); }
          .st-key-navigation [data-testid="stButton"] button { min-height: 46px; border-radius: 12px;
            font-weight: 700; padding: .55rem 1rem; }
          .st-key-navigation [data-testid="stButton"] button[kind="secondary"] {
            background: #fff; border-color: #bfd3dd; color: var(--ink) !important; }
          .st-key-navigation [data-testid="stButton"] button[kind="primary"],
          .hero [data-testid="stButton"] button[kind="primary"] { background: var(--blue) !important; color: #fff !important;
            border-color: var(--blue) !important; }
          .stButton button:focus { box-shadow: 0 0 0 3px rgba(14, 165, 198, .25) !important; }
          [data-baseweb="input"] input, [data-baseweb="textarea"] textarea,
          [data-baseweb="select"] > div { color: var(--ink) !important; background: #fff !important;
            border-color: var(--line) !important; }
          [data-baseweb="tag"] { color: var(--ink) !important; background: var(--soft-blue) !important; }
          @media (max-width: 640px) {
            .main .block-container { padding: 1.25rem .85rem 2.5rem; }
            .question-card { border-radius: 18px; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_welcome() -> None:
    st.markdown(
        """
        <section class="hero">
          <div style="font-size:4rem">✈️</div>
          <h1>AI Travel Planner</h1>
          <p>Tell us the feeling you want from your trip. We’ll handle the details.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    _, middle, _ = st.columns([1, 1.25, 1])
    with middle:
        if st.button("Start Planning", type="primary", use_container_width=True):
            st.session_state.screen = "questionnaire"
            st.rerun()


def main() -> None:
    apply_styles()
    if "screen" not in st.session_state:
        st.session_state.screen = "welcome"
    if "answers" not in st.session_state:
        st.session_state.answers = {}
    if "step" not in st.session_state:
        st.session_state.step = 0

    if st.session_state.screen == "welcome":
        render_welcome()
        render_groq_connection_test()
    elif st.session_state.screen == "results":
        render_results()
    else:
        render_questionnaire()


if __name__ == "__main__":
    main()
