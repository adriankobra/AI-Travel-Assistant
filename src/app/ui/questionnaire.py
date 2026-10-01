"""The guided, stateful questionnaire used in the first MVP phase."""

from __future__ import annotations

from datetime import date
from typing import Any

import streamlit as st

from app.ui.review import render_review


COUNTRIES_BY_CONTINENT = {
    "Europe": [
    "Italy",
    "Spain",
    "France",
    "Greece",
    "Croatia",
    "Portugal",
    "Germany",
    "Austria",
    "Switzerland",
    "Norway",
    "Sweden",
    "Finland",
    "Estonia",
    "Latvia",
    "Lithuania","Poland","Czech Republic","Hungary",],
    "Asia": ["Japan", "Thailand", "Vietnam", "Indonesia", "South Korea", "Singapore", "India", "Malaysia"],
    "North America": ["Canada", "United States", "Mexico", "Costa Rica"],
    "South America": ["Argentina", "Brazil", "Chile", "Colombia", "Peru"],
    "Africa": ["Morocco", "South Africa", "Tanzania", "Kenya", "Egypt"],
    "Oceania": ["Australia", "New Zealand", "Fiji"],
}

STEPS = [
    ("Where would you like to travel?", "continent"),
    ("Which countries appeal to you?", "countries"),
    ("What kind of trip do you want?", "trip_types"),
    ("What kind of travel experience do you prefer?", "travel_style"),
    ("What is your approximate budget?", "budget"),
    ("How long do you want to travel?", "duration"),
    ("Where would you like to stay?", "accommodation"),
    ("Who are you travelling with?", "travellers"),
    ("When would you like to travel?", "travel_period"),
    ("Where will your journey begin?", "origin"),
    ("How will you reach your destination?", "destination_transport"),
    ("How would you like to get around there?", "local_transport"),
    ("Anything else we should know?", "additional_preferences"),
]

STEP_DETAILS = [
    ("🌍", "Choose a continent to start planning your perfect trip."),
    ("🗺️", "Pick places you would love to explore."),
    ("✨", "Choose the moments you want your trip to be built around."),
    ("🧳", "Choose the level of comfort that feels right for you."),
    ("💶", "A clear range helps us create realistic estimated plans."),
    ("📅", "Tell us how much time you have for your adventure."),
    ("🏨", "Choose a stay that makes your trip feel just right."),
    ("👥", "Your travel party helps us tailor the experience."),
    ("☀️", "Let us know when you would like to get away."),
    ("🧭", "Your origin is kept separately from your destination."),
    ("🚆", "Choose a preferred journey mode; unavailable route facts stay unavailable."),
    ("🚗", "Tell us only the transport you can actually use."),
    ("💡", "A few finishing touches make a plan feel personal."),
]

CARD_EMOJIS = {
    "Europe": "🌍", "Asia": "🌏", "North America": "🌎", "South America": "🌎",
    "Africa": "🌍", "Oceania": "🏝️", "Other": "📍", "Budget": "🎒",
    "Comfortable": "🧳", "Premium": "✨", "Luxury": "💎", "🏨 Hotel": "🏨",
    "🏠 Apartment": "🏠", "🛏️ Hostel": "🛏️", "🏡 Guesthouse": "🏡",
    "⛺ Camping": "⛺", "🤷 Let AI choose": "🤖", "Solo": "🧍", "Couple": "💑",
    "Family": "👨‍👩‍👧", "Friends": "🧑‍🤝‍🧑", "Group": "👥",
}


def _save(key: str, value: Any) -> None:
    st.session_state.answers[key] = value


def _navigation(step: int) -> None:
    left, right = st.columns(2)
    with left:
        if step > 0 and st.button("← Back", use_container_width=True):
            st.session_state.step -= 1
            st.rerun()
    with right:
        label = "Review my trip →" if step == len(STEPS) - 1 else "Continue →"
        if st.button(label, type="primary", use_container_width=True):
            st.session_state.step += 1
            st.rerun()


def _card_label(option: str, selected: bool) -> str:
    """Give choices a compact travel-app card appearance without custom components."""
    icon = CARD_EMOJIS.get(option, option.split()[0] if option and ord(option[0]) > 1000 else "✦")
    text = option
    if text.startswith(icon):
        text = text[len(icon):].strip()
    return f"{icon}\n{text}{'  ✓' if selected else ''}"


def _option_step(key: str, options: list[str], *, multiple: bool = False) -> None:
    """Render Streamlit buttons as accessible selection cards backed by session state."""
    current = st.session_state.answers.get(key, [] if multiple else None)
    selected_values = list(current) if multiple else []
    columns_per_row = 2 if len(options) <= 8 else 3
    with st.container(key=f"choice-cards-{key}"):
        for start in range(0, len(options), columns_per_row):
            columns = st.columns(columns_per_row, gap="small")
            for column, option in zip(columns, options[start : start + columns_per_row]):
                selected = option in selected_values if multiple else option == current
                with column:
                    if st.button(
                        _card_label(option, selected),
                        key=f"choice-{key}-{option}",
                        type="primary" if selected else "secondary",
                        use_container_width=True,
                    ):
                        if multiple:
                            if option in selected_values:
                                selected_values.remove(option)
                            else:
                                selected_values.append(option)
                            _save(key, selected_values)
                        else:
                            if key == "continent" and option != current:
                                st.session_state.answers.pop("countries", None)
                                for widget_key in list(st.session_state):
                                    if widget_key.startswith("country_"):
                                        del st.session_state[widget_key]
                            _save(key, option)
                        st.rerun()


def _render_step(step: int) -> None:
    answers = st.session_state.answers
    if step == 0:
        _option_step("continent", ["Europe", "Asia", "North America", "South America", "Africa", "Oceania", "Other"])
        if answers.get("continent") == "Other":
            _save("continent_custom", st.text_input("Your destination region", value=answers.get("continent_custom", "")))
    elif step == 1:
        continent = answers.get("continent", "Europe")
        countries = COUNTRIES_BY_CONTINENT.get(continent, [])
        selected = [country for country in answers.get("countries", []) if country in countries]
        with st.popover("Search and choose countries", use_container_width=True):
            search = st.text_input("Search countries", key="country_search").casefold().strip()
            for country in countries:
                if search and search not in country.casefold():
                    continue
                checked = st.checkbox(country, value=country in selected, key=f"country_{country}")
                if checked and country not in selected:
                    selected.append(country)
                elif not checked and country in selected:
                    selected.remove(country)
            st.caption("Click outside this panel when your selection is complete.")
        st.caption("Selected: " + (", ".join(selected) if selected else "None yet"))
        surprise = st.checkbox("🎲 Surprise me", value=answers.get("surprise_me", False))
        other = st.text_input("Other country (optional)", value=answers.get("other_country", ""))
        _save("countries", selected)
        _save("surprise_me", surprise)
        _save("other_country", other)
    elif step == 2:
        _option_step("trip_types", ["🏖️ Beach & Relaxation", "🥾 Active Adventure", "🏛️ Sightseeing & Culture", "🍴 Food & Local Culture", "🎉 Nightlife", "🏔️ Nature & Mountains", "🛍️ Shopping", "🔀 Mixed Trip"], multiple=True)
    elif step == 3:
        _option_step("travel_style", ["Budget", "Comfortable", "Premium", "Luxury"])
    elif step == 4:
        _option_step("budget", ["Under €500", "€500–€800", "€800–€1,200", "€1,200–€2,000", "€2,000–€3,000", "€3,000+", "Custom"])
        if answers.get("budget") == "Custom":
            _save("custom_budget", st.number_input("Budget in EUR", min_value=1, value=int(answers.get("custom_budget", 1500))))
        _option_step("budget_scope", ["Per person", "For the whole trip"])
    elif step == 5:
        _option_step("duration", ["2–3 days", "4–5 days", "6–8 days", "9–14 days", "2+ weeks", "Custom"])
        if answers.get("duration") == "Custom":
            _save("custom_days", st.number_input("Number of days", min_value=1, max_value=90, value=int(answers.get("custom_days", 7))))
    elif step == 6:
        _option_step("accommodation", ["🏨 Hotel", "🏠 Apartment", "🛏️ Hostel", "🏡 Guesthouse", "⛺ Camping", "🤷 Let AI choose"])
        if answers.get("accommodation") == "🏨 Hotel":
            _option_step("hotel_category", ["No preference", "2★", "3★", "4★", "5★"])
    elif step == 7:
        _option_step("travellers", ["Solo", "Couple", "Family", "Friends", "Group"])
        _save("traveller_count", st.number_input("Number of travellers", min_value=1, max_value=30, value=int(answers.get("traveller_count", 1))))
    elif step == 8:
        _option_step("travel_period", ["Specific dates", "Specific month", "Flexible dates", "Let AI choose the best period"])
        period = answers.get("travel_period")
        if period == "Specific dates":
            _save("dates", st.date_input("Travel dates", value=answers.get("dates", (date.today(), date.today()))))
        elif period == "Specific month":
            _save("month", st.text_input("Month and year", value=answers.get("month", "June 2027")))
    elif step == 9:
        _save("origin", st.text_input("City or region you are travelling from (optional)", value=answers.get("origin", ""), placeholder="For example: Riga, Tallinn or Berlin"))
    elif step == 10:
        _option_step("destination_transport", ["Plane", "Car", "Bus", "Train", "Motorcycle", "Flexible / let planner decide"])
        if answers.get("destination_transport") in {"Car", "Motorcycle"}:
            _option_step("journey_vehicle", ["Own vehicle", "Rental vehicle"])
            _save("fuel_consumption_l_per_100km", st.number_input("Vehicle fuel consumption (L / 100 km, optional)", min_value=0.0, max_value=50.0, value=float(answers.get("fuel_consumption_l_per_100km", 0.0)), step=0.1, help="Enter your vehicle's consumption. Leave at 0 if unknown."))
            _save("fuel_price_eur_per_litre", st.number_input("Fuel price you want to assume (EUR / litre, optional)", min_value=0.0, max_value=10.0, value=float(answers.get("fuel_price_eur_per_litre", 0.0)), step=0.01, help="Enter a price you know or want to use as an assumption. The planner does not fetch live fuel prices."))
        else:
            # Do not silently carry driving cost assumptions into a later
            # train, bus or plane itinerary when an answer is changed.
            for field in ("journey_vehicle", "fuel_consumption_l_per_100km", "fuel_price_eur_per_litre"):
                answers.pop(field, None)
    elif step == 11:
        _option_step("local_transport", ["Walking / mostly walking", "Public transport", "Own car", "Rental car", "Bicycle", "Motorcycle", "Mixed transport"])
        _save("driving_license", st.checkbox("I have a driving licence", value=bool(answers.get("driving_license", False))))
        _save("own_car", st.checkbox("I have my own car available", value=bool(answers.get("own_car", False))))
        _save("rental_car_allowed", st.checkbox("I can rent a car", value=bool(answers.get("rental_car_allowed", False))))
        _save("rental_bicycle_allowed", st.checkbox("I can rent a bicycle", value=bool(answers.get("rental_bicycle_allowed", False))))
    else:
        _option_step("additional_preferences", ["🌊 Near the sea", "🏔️ Near mountains", "🚗 Road trip", "🚆 Prefer public transport", "🚶 Walking-friendly", "🌡️ Warm weather", "🏙️ Big city", "🌿 Nature", "📸 Instagram-worthy places", "👨‍👩‍👧 Family-friendly", "💑 Romantic", "🎒 Backpacking"], multiple=True)
        _save("notes", st.text_area("Anything else? (optional)", value=answers.get("notes", ""), max_chars=500))
        _save("trip_constraints", st.text_area("Trip preferences & constraints (optional)", value=answers.get("trip_constraints", ""), max_chars=500, help="For example: at least 3 hours of free time each day; no more than 90 minutes of travel."))
        _save("budget_request", st.text_area("Trip budget (optional)", value=answers.get("budget_request", ""), max_chars=300, help="For example: €800 for 2 people excluding flights, or no more than €100 per day."))


def render_questionnaire() -> None:
    """Render either the current question or the review screen."""
    step = st.session_state.step
    if step >= len(STEPS):
        render_review()
        return

    question, _ = STEPS[step]
    icon, description = STEP_DETAILS[step]
    st.markdown(
        f'<div class="app-brand"><div class="eyebrow">✈️ AI TRAVEL PLANNER</div>'
        f'<p>Plan your next adventure</p></div>',
        unsafe_allow_html=True,
    )
    progress = (step + 1) / len(STEPS) * 100
    st.markdown(
        f'<div class="travel-progress-label">Step {step + 1} of {len(STEPS)}</div>'
        f'<div class="travel-progress-track" style="background:#d9eaf1 !important">'
        f'<span class="travel-progress-fill" style="width:{progress}%; background:#0ea5c6 !important"></span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="question-card"><div class="question-icon">{icon}</div>'
        f'<h2 style="text-align:center">{question}</h2>'
        f'<p class="question-intro">{description}</p>',
        unsafe_allow_html=True,
    )
    _render_step(step)
    st.markdown("</div>", unsafe_allow_html=True)
    with st.container(key="navigation"):
        _navigation(step)
