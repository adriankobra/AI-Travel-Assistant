"""Review page for questionnaire answers before the AI workflow is connected."""

import streamlit as st

from app.ai.travel_agent import TravelAgent, TravelAgentError


def _display(value: object, fallback: str = "Not selected") -> str:
    if isinstance(value, list):
        return ", ".join(value) if value else fallback
    return str(value) if value else fallback


def render_review() -> None:
    """Show a readable, editable summary of the user's answers."""
    answers = st.session_state.answers
    st.title("Your trip at a glance")
    st.caption("Review your choices before we generate your travel options.")

    cards = [
        ("🌍 Destination", _display(answers.get("continent")), _display(answers.get("countries"))),
        ("✨ Trip type", _display(answers.get("trip_types")), _display(answers.get("travel_style"))),
        ("💶 Budget", _display(answers.get("custom_budget") if answers.get("budget") == "Custom" else answers.get("budget")), _display(answers.get("budget_scope"))),
        ("📅 Timing", _display(answers.get("duration")), _display(answers.get("travel_period"))),
        ("🏨 Stay", _display(answers.get("accommodation")), _display(answers.get("hotel_category"))),
        ("👥 Travellers", _display(answers.get("travellers")), f"{answers.get('traveller_count', 1)} traveller(s)"),
        ("🧭 Journey", _display(answers.get("origin")), _display(answers.get("destination_transport")) + (f" · {answers['journey_vehicle']}" if answers.get("journey_vehicle") and answers.get("destination_transport") in {"Car", "Motorcycle"} else "")),
        ("🚗 Local mobility", _display(answers.get("local_transport")), "Capabilities saved for planning"),
    ]
    for row in range(0, len(cards), 3):
        columns = st.columns(3)
        for column, (title, primary, secondary) in zip(columns, cards[row : row + 3]):
            with column:
                st.markdown(f'<div class="summary-card"><strong>{title}</strong><br><br>{primary}<br><small>{secondary}</small></div>', unsafe_allow_html=True)

    st.subheader("Additional preferences")
    st.write(_display(answers.get("additional_preferences")))
    if answers.get("notes"):
        st.caption(f"Note: {answers['notes']}")
    if answers.get("trip_constraints"):
        st.caption(f"Constraints: {answers['trip_constraints']}")
    if answers.get("budget_request"):
        st.caption(f"Budget request: {answers['budget_request']}")
    if answers.get("destination_transport") in {"Car", "Motorcycle"} and answers.get("fuel_consumption_l_per_100km"):
        st.caption(f"Fuel assumptions: {answers['fuel_consumption_l_per_100km']:g} L/100 km · €{answers.get('fuel_price_eur_per_litre', 0):g}/L (user supplied)")

    left, right = st.columns(2)
    with left:
        if st.button("← Edit answers", use_container_width=True):
            st.session_state.step = 0
            st.rerun()
    with right:
        if st.button("✈️ Generate my trips", type="primary", use_container_width=True):
            with st.spinner("Creating five travel options just for you..."):
                try:
                    plans = TravelAgent().generate_options(answers)
                except TravelAgentError as error:
                    st.error(str(error))
                else:
                    # The detailed recommender runs on the results page, after
                    # this widget callback has finished.  Persist an immutable
                    # snapshot of the review answers before switching screens;
                    # otherwise it would see an empty preference set on a later
                    # Streamlit rerun.
                    st.session_state.travel_preferences = dict(answers)
                    st.session_state.travel_plans = plans
                    st.session_state.selected_plan_index = None
                    st.session_state.screen = "results"
                    st.rerun()
