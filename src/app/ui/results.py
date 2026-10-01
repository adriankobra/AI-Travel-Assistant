"""
Results UI for AI travel recommendations and real travel plans.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.travel.travel_data import get_travel_data
from app.ai.travel_recommender import TravelRecommender
from app.reporting.pdf_report import PDFReportError, build_pdf_report
from app.travel.map_links import build_location_map_url, build_multi_stop_map_url, build_route_map_url
from app.ui.itinerary_map import render_itinerary_map
from app.travel.plan_consistency import validate_plan_consistency
from app.travel.component_replacement import ComponentReplacementError, move_activity, remove_activity, replace_activity, replace_food, replace_hotel
from app.travel.routing_openrouteservice import OpenRouteServiceRoutingService
from app.travel.budget import TripBudget, budget_summary
from app.travel.control_center import place_explanation, preference_influence, quality_indicators, trip_overview
from app.ai.mobility_analyzer import MobilityAnalyzer
from app.travel.mobility import discovery_radius_meters


def _money(value: Any) -> str:
    """Format estimated money values."""
    if isinstance(value, (int, float)):
        return f"€{value:,.0f}"

    return "Estimate unavailable"


def _clean_day_title(
    day_number: int,
    title: str,
) -> str:
    """
    Remove duplicated day number from the AI title.

    Examples:
        Day 1 -> ""
        Day 1: Culture -> "Culture"
        Day 1 - Culture -> "Culture"
        Day 1 — Culture -> "Culture"
        Culture -> "Culture"
    """

    title = str(title).strip()

    normalized = title.lower()

    exact_day = f"day {day_number}"

    if normalized == exact_day:
        return ""

    colon_prefix = f"day {day_number}:"

    if normalized.startswith(colon_prefix):
        return title.split(":", 1)[1].strip()

    dash_prefix = f"day {day_number} -"

    if normalized.startswith(dash_prefix):
        return title.split("-", 1)[1].strip()

    long_dash_prefix = f"day {day_number} —"

    if normalized.startswith(long_dash_prefix):
        return title.split("—", 1)[1].strip()

    return title


def _generate_real_recommendations(
    plan: dict[str, Any],
) -> dict[str, Any]:
    """
    Get real places from Geoapify and let the AI
    build a real itinerary from those places.
    """

    travel_preferences = st.session_state.get(
        "travel_preferences",
        {},
    )

    accommodation_type = plan.get(
        "accommodation_type",
        "Hotel",
    )

    accommodation_mapping = {
        "hotel": "Hotel",
        "🏨 hotel": "Hotel",

        "apartment": "Apartment",
        "🏠 apartment": "Apartment",

        "hostel": "Hostel",
        "🛏️ hostel": "Hostel",

        "guesthouse": "Guesthouse",
        "🏡 guesthouse": "Guesthouse",

        "camping": "Camping",
        "⛺ camping": "Camping",

        "let ai choose": "Hotel",
        "🤷 let ai choose": "Hotel",
    }

    accommodation_text = str(
        accommodation_type
    ).strip().lower()

    accommodation_type = accommodation_mapping.get(
        accommodation_text,
        accommodation_type,
    )

    city = plan["destination"]
    country = plan["country"]

    duration_days = int(
        plan.get("duration_days", 1)
    )

    # Broaden factual discovery only when the declared local mobility makes a
    # regional itinerary plausible. Selection and route validation remain
    # independent safeguards.
    from app.travel.mobility import MobilityProfile
    mobility = MobilityAnalyzer._apply_explicit_questionnaire_signals(MobilityProfile.unknown(), travel_preferences)
    activity_radius = discovery_radius_meters(mobility)
    travel_data = get_travel_data(
        city=city,
        country=country,
        accommodation_type=accommodation_type,
        accommodation_limit=5,
        activity_limit=120 if activity_radius >= 30_000 else 80 if activity_radius >= 12_000 else 60,
        activity_radius=activity_radius,
    )

    recommender = TravelRecommender()

    return recommender.recommend(
        preferences=travel_preferences,
        destination={
            "city": city,
            "country": country,
        },
        travel_data=travel_data,
        duration_days=duration_days,
    )


def _regenerate_real_plan(current: dict[str, Any], *, replace_hotel: bool) -> dict[str, Any]:
    """Build a complete candidate first; callers replace session state only on success."""
    context = current.get("validation_context", {})
    travel_data = context.get("travel_data")
    destination = current.get("destination")
    duration_days = context.get("duration_days")
    if not isinstance(travel_data, dict) or not isinstance(destination, dict) or not isinstance(duration_days, int):
        raise ValueError("The saved plan is missing its verified regeneration context.")
    current_hotel = current.get("selected_accommodation", {}).get("name") if isinstance(current.get("selected_accommodation"), dict) else None
    previous_activities = {
        item.get("name") for day in current.get("itinerary", []) if isinstance(day, dict)
        for item in day.get("activities", []) if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    candidate = TravelRecommender().recommend(
        preferences=st.session_state.get("travel_preferences", {}), destination=destination,
        travel_data=travel_data, duration_days=duration_days,
        excluded_accommodation_names={current_hotel} if replace_hotel and isinstance(current_hotel, str) else set(),
        excluded_activity_names=previous_activities if not replace_hotel else set(),
    )
    if replace_hotel and candidate.get("selected_accommodation", {}).get("name") == current_hotel:
        raise ValueError("No different verified accommodation candidate was available.")
    validate_plan_consistency(candidate)
    return candidate


def _render_real_itinerary(
    recommendations: dict[str, Any],
    cache_key: str,
) -> None:
    """Display the real accommodation and real itinerary."""

    st.divider()

    st.subheader("📍 Your real travel plan")

    _render_control_center(recommendations, cache_key)
    _render_preference_evidence(recommendations)
    _render_trip_strategy(recommendations)
    _render_constraints(recommendations)
    _render_budget(recommendations, cache_key)

    accommodation = recommendations.get(
        "selected_accommodation"
    )

    if isinstance(accommodation, dict):

        st.markdown("### 🏨 Accommodation")

        accommodation_name = accommodation.get(
            "name",
            "Accommodation",
        )

        st.markdown(
            f"**{accommodation_name}**"
        )

        accommodation_address = accommodation.get(
            "address",
            "Address unavailable",
        )

        st.caption(
            accommodation_address
        )

        reason = accommodation.get(
            "reason",
            "",
        )

        if reason:
            st.write(
                f"**Why it matches:** {reason}"
            )
        with st.expander("Why was this hotel selected?", expanded=False):
            for explanation in place_explanation(recommendations, accommodation, "accommodation"):
                st.write(f"- {explanation}")

        maps_url = build_location_map_url(accommodation)
        if maps_url:
            st.markdown(f"[🗺️ View location]({maps_url})")

        st.markdown("#### Smart alternatives")
        replace, regenerate, variation = st.columns(3)
        with replace:
            replace_requested = st.button("🔄 Replace hotel", key=f"replace-hotel-{cache_key}", use_container_width=True)
        with regenerate:
            regenerate_requested = st.button("🔄 Regenerate itinerary", key=f"regenerate-itinerary-{cache_key}", use_container_width=True)
        with variation:
            variation_requested = st.button("✨ Build another version of this trip", key=f"variation-{cache_key}", use_container_width=True)
        if replace_requested or regenerate_requested or variation_requested:
            try:
                with st.spinner("Building and validating a replacement plan..."):
                    # A variation deliberately excludes previous activities;
                    # the previous validated snapshot remains untouched until
                    # this complete candidate passes validation.
                    candidate = (
                        replace_hotel(recommendations, st.session_state.get("travel_preferences", {}), OpenRouteServiceRoutingService())
                        if replace_requested else _regenerate_real_plan(recommendations, replace_hotel=False)
                    )
                # Assignment happens only after recommender + validator succeed.
                st.session_state[cache_key] = candidate
                st.success("A new validated real plan is ready.")
                st.rerun()
            except Exception as error:
                st.warning(f"Your current validated plan was kept. Regeneration was unavailable: {error}")

    st.markdown("### 🗓️ Day-by-day controls")

    _render_itinerary_editor(recommendations, cache_key)

    itinerary = recommendations.get(
        "itinerary",
        [],
    )

    render_itinerary_map(accommodation if isinstance(accommodation, dict) else None, itinerary)
    st.caption("Map markers use verified place coordinates. Dashed connections show itinerary order, not ORS route geometry.")

    for day in itinerary:

        day_number = day.get(
            "day",
            1,
        )

        title = _clean_day_title(
            day_number,
            day.get("title", ""),
        )

        if title:
            day_label = (
                f"Day {day_number} — {title}"
            )
        else:
            day_label = f"Day {day_number}"

        with st.expander(
            day_label,
            expanded=day_number == 1,
        ):

            regional = day.get("regional_trip")
            if isinstance(regional, dict) and isinstance(regional.get("distance_from_accommodation_meters"), (int, float)):
                distance = regional["distance_from_accommodation_meters"] / 1000
                mode = str(regional.get("transport_mode", "selected mode")).replace("_", " ")
                round_trip = regional.get("round_trip_distance_meters")
                if regional.get("status") == "verified" and isinstance(round_trip, (int, float)):
                    st.info(f"Regional day trip · {regional.get('anchor')} and {regional.get('companion')} are verified Geoapify places. ORS verifies the first leg at {distance:.1f} km from the accommodation and the planned round trip at {round_trip / 1000:.1f} km by {mode}.")
                else:
                    st.info(f"Regional day trip · {regional.get('anchor')} and {regional.get('companion')} are verified Geoapify places. ORS car-road distance to the first stop is {distance:.1f} km; motorcycle access and duration are unverified.")

            schedule = day.get("schedule", {})
            if isinstance(schedule, dict):
                st.caption(
                    f"Approximate schedule · {len(day.get('activities', []))} activities · "
                    f"{schedule.get('free_time_minutes', 'unavailable')} min free time"
                )

            route_url = build_multi_stop_map_url(day.get("route_stops", []), _day_mode(day))
            if route_url:
                st.markdown(f"[🗺️ Open full day route]({route_url})")
            elif day.get("route_stops"):
                st.caption("A single route link is unavailable because one or more stops lack coordinates or the route is too long.")
            for item in day.get("items", []):
                if isinstance(item, dict):
                    _render_timeline_item(item, recommendations, cache_key, day_number)
            return_route = day.get("return_route")
            if day.get("travel_constraint_note"):
                st.warning(str(day["travel_constraint_note"]))
            if day.get("mobility_warning"):
                st.warning(str(day["mobility_warning"]))
            if isinstance(return_route, dict) and return_route.get("data_status") == "verified" and isinstance(return_route.get("distance_meters"), (int, float)):
                st.caption(f"Return to accommodation: {float(return_route['distance_meters']) / 1000:.1f} km ORS road route; {return_route['duration_minutes']} min by {return_route.get('transport_mode', 'selected mode')}. This leg has no assigned departure time.")

    st.divider()
    try:
        pdf = build_pdf_report(recommendations, st.session_state.get("travel_preferences", {}))
        st.download_button("Download PDF travel report", pdf, file_name="ai-travel-plan.pdf", mime="application/pdf", use_container_width=True)
    except PDFReportError as error:
        st.warning(f"PDF export is unavailable until this itinerary validates: {error}")


def _day_mode(day: dict[str, Any]) -> str | None:
    for item in day.get("items", []):
        if isinstance(item, dict) and item.get("item_type") == "travel" and isinstance(item.get("transport_mode"), str):
            return item["transport_mode"]
    return None


def _render_itinerary_editor(plan: dict[str, Any], cache_key: str) -> None:
    """Small reliable editor; candidate plans replace session state only on success."""
    choices = [
        (int(day.get("day", 0)), str(activity.get("name")))
        for day in plan.get("itinerary", []) if isinstance(day, dict)
        for activity in day.get("activities", []) if isinstance(activity, dict) and isinstance(activity.get("name"), str)
    ]
    if not choices:
        return
    with st.expander("Edit itinerary", expanded=False):
        labels = {f"Day {day}: {name}": (day, name) for day, name in choices}
        selected_label = st.selectbox("Activity to edit", list(labels), key=f"edit-activity-{cache_key}")
        source_day, activity_name = labels[selected_label]
        target_day = st.selectbox("Move to day", [int(day.get("day")) for day in plan.get("itinerary", []) if isinstance(day, dict)], key=f"edit-target-day-{cache_key}")
        move, remove = st.columns(2)
        move_requested = move.button("Move activity", key=f"move-activity-{cache_key}")
        remove_requested = remove.button("Remove activity", key=f"remove-activity-{cache_key}")
        if not (move_requested or remove_requested):
            return
        try:
            routing = OpenRouteServiceRoutingService()
            preferences = st.session_state.get("travel_preferences", {})
            candidate = (
                move_activity(plan, activity_name, source_day, target_day, preferences, routing)
                if move_requested else remove_activity(plan, source_day, activity_name, preferences, routing)
            )
            st.session_state[cache_key] = candidate
            st.success("The edited itinerary was rebuilt and validated.")
            st.rerun()
        except ComponentReplacementError as error:
            st.warning(f"Your current validated plan was kept: {error}")


def _render_preference_evidence(recommendations: dict[str, Any]) -> None:
    """Show transparent preference evidence without treating it as place facts."""
    selected = recommendations.get("selected_place_ranking", {})
    activity_evidence = selected.get("activities", []) if isinstance(selected, dict) else []
    matched = []
    for item in activity_evidence:
        if isinstance(item, dict):
            matched.extend(value for value in item.get("matched_concepts", []) if isinstance(value, str))
    matched = list(dict.fromkeys(matched))
    unmet = recommendations.get("unverified_activity_preference_concepts", [])
    if not matched and not unmet:
        return
    with st.expander("Your preferences influenced this trip", expanded=True):
        influence = preference_influence(recommendations)
        if influence:
            for item in influence:
                st.write("• " + item)
        else:
            st.caption("No verified category-to-preference match was available to show for this trip.")
        if matched:
            st.caption("Verified Geoapify category matches: " + ", ".join(value.replace("_", " ") for value in matched) + ".")
        if unmet:
            st.caption("No verified Geoapify match was found for: " + ", ".join(str(value).replace("_", " ") for value in unmet) + ". The plan does not claim those services exist.")


def _render_control_center(plan: dict[str, Any], cache_key: str) -> None:
    """An actionable read model for one already validated itinerary snapshot."""
    preferences = st.session_state.get("travel_preferences", {})
    overview = trip_overview(plan, preferences)
    st.subheader("Smart Trip Control Center")
    first, second, third = st.columns(3)
    first.metric("Destination", overview["destination"])
    second.metric("Hotel", overview["hotel"])
    third.metric("Trip", f"{overview['days']} day(s) · {str(overview['pace']).title()} pace")
    st.caption(f"Style: {overview['travel_style']} · Mobility: {str(overview['mobility'].get('preferred_transport') or 'not specified').replace('_', ' ')}")
    journey = overview.get("journey", {})
    if journey.get("origin") or journey.get("requested_mode"):
        st.markdown("#### Getting there & local transport")
        vehicle = f" · {journey['journey_vehicle']}" if journey.get("journey_vehicle") else ""
        st.write(f"{journey.get('origin') or 'Origin not specified'} → {journey.get('destination') or 'destination'} · **{journey.get('requested_mode') or 'Flexible'}{vehicle}**")
        for label, key in (("Outbound", "outbound"), ("Return", "return")):
            leg = journey.get(key, {})
            if not isinstance(leg, dict):
                continue
            distance = leg.get("distance_meters")
            route_text = f"{float(distance) / 1000:.1f} km ORS road distance" if isinstance(distance, (int, float)) else "route distance unavailable"
            duration = leg.get("duration_minutes")
            if isinstance(duration, int):
                route_text += f" · {duration} min ORS car route"
            fuel = leg.get("fuel_cost_eur")
            if isinstance(fuel, (int, float)):
                route_text += f" · €{fuel:.2f} calculated fuel"
            st.write(f"**{label}:** {route_text} · {leg.get('status', 'unavailable')}")
        st.caption(str(journey.get("note") or "Journey price data unavailable."))
        st.caption(f"Local mobility: {str(overview['mobility'].get('preferred_transport') or 'not specified').replace('_', ' ')}. Day routes below show verified ORS legs when available.")
    with st.expander("What the planner understood", expanded=False):
        priorities = overview["priorities"]
        avoidances = overview["avoidances"]
        if priorities:
            st.write("Priorities: " + ", ".join(str(item).replace("_", " ") for item in priorities) + ".")
        if avoidances:
            st.write("Avoiding: " + ", ".join(str(item).replace("_", " ") for item in avoidances) + ".")
        if overview["important_preferences"]:
            st.write("Original preferences: " + " · ".join(str(item) for item in overview["important_preferences"]))
        if overview["dates"]:
            st.write("Trip dates: " + " to ".join(str(item) for item in overview["dates"]))
        if not priorities and not overview["important_preferences"]:
            st.caption("No additional natural-language preference was stored for this trip.")
    with st.expander("Trip quality indicators", expanded=False):
        for indicator in quality_indicators(plan):
            st.write(f"**{indicator['label']}:** {indicator['status']}")
    st.caption("Edits are transactional: the current plan stays visible unless a rebuilt candidate validates.")


def _render_trip_strategy(recommendations: dict[str, Any]) -> None:
    strategy = recommendations.get("trip_strategy")
    if not isinstance(strategy, dict):
        return
    primary = [str(value).replace("_", " ") for value in strategy.get("primary_concepts", [])]
    avoided = [str(value).replace("_", " ") for value in strategy.get("avoided_concepts", [])]
    with st.expander("How this trip is planned", expanded=False):
        st.write(f"Pace: **{str(strategy.get('pace', 'balanced')).title()}**")
        if primary:
            st.write("Priorities: " + ", ".join(primary) + ".")
        if avoided:
            st.write("Avoiding where verified categories conflict: " + ", ".join(avoided) + ".")


def _render_constraints(recommendations: dict[str, Any]) -> None:
    from app.travel.constraints import TripConstraints
    constraints = TripConstraints.from_dict(recommendations.get("trip_constraints"))
    understood = constraints.understood()
    fit = recommendations.get("plan_fit", [])
    if not understood and not fit:
        return
    with st.expander("Trip constraints", expanded=False):
        st.write(" · ".join(understood) if understood else "No explicit practical constraints were understood.")
    if fit:
        with st.expander("Plan fit", expanded=False):
            for item in fit:
                if isinstance(item, dict):
                    st.write(f"**{item.get('constraint', 'Constraint')}:** {item.get('status', 'unavailable to verify')}")


def _render_budget(recommendations: dict[str, Any], cache_key: str) -> None:
    """Expose an editable, factual budget view without manufacturing totals."""
    preferences = st.session_state.get("travel_preferences", {})
    budget = TripBudget.from_dict(recommendations.get("trip_budget"))
    summary = recommendations.get("budget_summary")
    if not isinstance(summary, dict):
        summary = budget_summary(recommendations, budget)
    with st.expander("Budget", expanded=False):
        current_text = str(preferences.get("budget_request", ""))
        new_text = st.text_input("Budget request", value=current_text, key=f"budget-request-{cache_key}", placeholder="€800 for 2 people excluding flights")
        if st.button("Update budget", key=f"update-budget-{cache_key}"):
            updated_preferences = dict(preferences)
            updated_preferences["budget_request"] = new_text
            updated_budget = TripBudget.from_preferences(updated_preferences)
            recommendations["trip_budget"] = updated_budget.to_dict()
            recommendations["budget_summary"] = budget_summary(recommendations, updated_budget)
            st.session_state["travel_preferences"] = updated_preferences
            st.session_state[cache_key] = recommendations
            st.rerun()
        label = budget.understood() or "No explicit budget was understood."
        st.write(label)
        costs = summary.get("verified_costs", {})
        calculated = summary.get("calculated_costs", {})
        labels = {
            "transport_to_destination": "Getting there", "return_journey": "Return journey",
            "local_transport": "Local transport", "accommodation": "Accommodation",
            "food": "Food", "activities": "Activities",
        }
        for key, title in labels.items():
            verified = costs.get(key) if isinstance(costs, dict) else None
            estimated = calculated.get(key) if isinstance(calculated, dict) else None
            if isinstance(verified, (int, float)):
                st.write(f"**{title}:** €{verified:,.2f} · verified provider price")
            elif isinstance(estimated, (int, float)):
                st.write(f"**{title}:** €{estimated:,.2f} · calculated fuel estimate")
            else:
                st.write(f"**{title}:** price unavailable")
        if isinstance(summary.get("accounted_subtotal_eur"), (int, float)):
            st.caption(f"Known and calculated subtotal: €{summary['accounted_subtotal_eur']:,.2f}. This is not a full trip total.")
        if isinstance(calculated, dict) and any(isinstance(value, (int, float)) for value in calculated.values()):
            st.caption(str(summary.get("calculation_note", "")))
        unknown = summary.get("unknown_categories", [])
        if unknown:
            st.caption("Unknown: " + ", ".join(str(item) for item in unknown) + ".")
        st.write(f"**Status:** {summary.get('status', 'price data unavailable')}")


def _render_timeline_item(item: dict[str, Any], plan: dict[str, Any], cache_key: str, day_number: int) -> None:
    item_type = item.get("item_type")
    time_label = " - ".join(value for value in (item.get("start_time"), item.get("end_time")) if isinstance(value, str))
    if item_type == "travel":
        if item.get("travel_time_data_status") == "verified":
            mode = item.get("requested_transport_mode") or item.get("transport_mode") or "Travel"
            icon = "🚗" if mode == "car" else "🏍️" if mode == "motorcycle" else "🚴" if mode == "bicycle" else "🚶"
            note = f" ({item['route_mode_note']})" if item.get("route_mode_note") else ""
            verification = "Verified ORS car-road profile; motorcycle travel time not verified" if mode == "motorcycle" else "Verified by OpenRouteService"
            st.write(f"{time_label} - {icon} **{str(mode).replace('_', ' ').title()}**: {item.get('travel_duration_minutes')} min / {item.get('travel_distance_meters')} m - {verification}{note}")
            route_url = build_route_map_url(item.get("origin", {}), item.get("destination", {}), item.get("transport_mode"))
            if route_url:
                st.markdown(f"[Open route]({route_url})")
        else:
            st.caption(f"{time_label} - Travel planning buffer: {item.get('planning_buffer_minutes', 'unavailable')} min (Estimated; route data unavailable)")
        return
    if item_type == "meal":
        st.markdown(f"🍽️ **{str(item.get('meal_type', 'Meal')).title()}** - {time_label or 'time flexible'}")
        options = item.get("options", [])
        if not options:
            st.caption("No verified Geoapify food option was found for this stop.")
        for option in options:
            if not isinstance(option, dict):
                continue
            detail = option.get("name", "Food option")
            if option.get("travel_time_data_status") == "verified":
                detail += f" - {option.get('travel_duration_minutes')} min walking/travel, {option.get('travel_distance_meters')} m (Verified ORS)"
            else:
                detail += " - route information unavailable"
            st.write(f"• {detail}")
            url = build_location_map_url(option)
            if url:
                st.markdown(f"[View location]({url})")
        if options and item.get("meal_type") in {"lunch", "dinner"}:
            if st.button(f"🔄 Replace {item['meal_type']}", key=f"replace-food-{cache_key}-{day_number}-{item['meal_type']}"):
                try:
                    candidate = replace_food(plan, day_number, item["meal_type"], st.session_state.get("travel_preferences", {}), OpenRouteServiceRoutingService())
                    st.session_state[cache_key] = candidate
                    st.rerun()
                except ComponentReplacementError as error:
                    st.warning(f"Your current food option was kept: {error}")
        return
    if item_type == "free_time":
        st.caption(f"Free time: {item.get('duration_minutes')} min")
        return
    if item_type == "accommodation":
        st.markdown(f"🏨 **Accommodation base:** {item.get('name', 'Accommodation')} - {time_label or 'available'}")
        if item.get("address"):
            st.caption(str(item["address"]))
        url = build_location_map_url(item)
        if url:
            st.markdown(f"[View hotel location]({url})")
        return
    st.markdown(f"📍 **{item.get('name', 'Activity')}** - {time_label}")
    st.caption(item.get("address", "Address unavailable"))
    if item.get("reason"):
        st.write(item["reason"])
    with st.expander("Why was this selected?", expanded=False):
        for explanation in place_explanation(plan, item, "activity"):
            st.write(f"- {explanation}")
    duration_status = "Verified" if item.get("duration_data_status") == "verified" else "Estimated planning duration"
    st.caption(f"{item.get('duration_minutes')} min - {duration_status}")
    url = build_location_map_url(item)
    if url:
        st.markdown(f"[View location]({url})")
    if st.button("🔄 Replace activity", key=f"replace-activity-{cache_key}-{day_number}-{item.get('name', '')}"):
        try:
            candidate = replace_activity(plan, day_number, str(item.get("name", "")), st.session_state.get("travel_preferences", {}), OpenRouteServiceRoutingService())
            st.session_state[cache_key] = candidate
            st.rerun()
        except ComponentReplacementError as error:
            st.warning(f"Your current activity was kept: {error}")


def _render_plan_details(
    plan: dict[str, Any],
) -> None:
    """Display details of the selected AI travel option."""

    st.divider()

    st.subheader(
        f"{plan['destination']}, "
        f"{plan['country']}"
    )

    st.caption(
        "All prices are approximate estimates, "
        "not live quotes or availability."
    )

    st.write(
        plan["short_description"]
    )

    st.markdown(
        f"**Why this matches you:** "
        f"{plan['why_it_matches']}"
    )

    st.markdown(
        f"💰 **Estimated total:** "
        f"{_money(plan['estimated_total_budget'])}"
    )

    st.markdown(
        f"📅 **Duration:** "
        f"{plan['duration_days']} days"
    )

    st.markdown(
        f"🏨 **Accommodation:** "
        f"{plan['accommodation_type']}"
    )

    st.markdown(
        f"✨ **Travel style:** "
        f"{plan['travel_style']}"
    )

    st.markdown(
        "**Suggested activities:** "
        + " · ".join(
            plan["main_activities"]
        )
    )

    # ============================================
    # BUILD REAL PLAN
    # ============================================

    st.divider()

    button_key = (
        f"build-real-plan-"
        f"{plan['destination']}-"
        f"{plan['country']}"
    )

    if st.button(
        "🌍 Build real travel plan",
        key=button_key,
        use_container_width=True,
        type="primary",
    ):

        try:

            with st.spinner(
                "Finding real places and building your itinerary..."
            ):

                recommendations = (
                    _generate_real_recommendations(
                        plan
                    )
                )

            cache_key = (
                f"real_recommendations_"
                f"{plan['destination']}_"
                f"{plan['country']}"
            )

            st.session_state[
                cache_key
            ] = recommendations

            st.rerun()

        except Exception as error:

            st.error(
                f"Could not build the real travel plan: "
                f"{error}"
            )

    # ============================================
    # SHOW REAL PLAN
    # ============================================

    cache_key = (
        f"real_recommendations_"
        f"{plan['destination']}_"
        f"{plan['country']}"
    )

    real_recommendations = (
        st.session_state.get(
            cache_key
        )
    )

    if real_recommendations:

        _render_real_itinerary(real_recommendations, cache_key)


def render_results() -> None:
    """
    Display generated AI travel options
    and the selected detailed plan.
    """

    plans = st.session_state.get(
        "travel_plans",
        [],
    )

    if not plans:

        st.warning(
            "No travel options are available yet. "
            "Generate a trip from the review screen first."
        )

        if st.button(
            "← Return to my trip review"
        ):

            st.session_state.screen = (
                "questionnaire"
            )

            st.session_state.step = 10

            st.rerun()

        return

    # ============================================
    # PAGE HEADER
    # ============================================

    st.title(
        "Your AI travel options"
    )

    st.caption(
        "Five different ideas shaped by your "
        "preferences. Prices are estimates, "
        "not real-time quotes."
    )

    # ============================================
    # FIVE AI OPTIONS
    # ============================================

    for index, plan in enumerate(plans):

        with st.container(
            border=True
        ):

            left, right = st.columns(
                [3, 1]
            )

            with left:

                st.subheader(
                    f"🌍 "
                    f"{plan['destination']}, "
                    f"{plan['country']}"
                )

                st.write(
                    plan["short_description"]
                )

                st.markdown(
                    f"**Why this matches you:** "
                    f"{plan['why_it_matches']}"
                )

                st.caption(
                    "Activities: "
                    + " · ".join(
                        plan["main_activities"]
                    )
                )

            with right:

                st.markdown(
                    f"**💰 "
                    f"{_money(plan['estimated_total_budget'])}**"
                )

                st.caption(
                    "Estimated total"
                )

                st.write(
                    f"📅 "
                    f"{plan['duration_days']} days"
                )

                st.write(
                    f"🏨 "
                    f"{plan['accommodation_type']}"
                )

                st.write(
                    f"✨ "
                    f"{plan['travel_style']}"
                )

                if st.button(
                    "View full plan",
                    key=f"view-plan-{index}",
                    use_container_width=True,
                ):

                    st.session_state[
                        "selected_plan_index"
                    ] = index

                    st.rerun()

    # ============================================
    # SELECTED PLAN
    # ============================================

    selected_index = (
        st.session_state.get(
            "selected_plan_index"
        )
    )

    if (
        isinstance(selected_index, int)
        and 0 <= selected_index < len(plans)
    ):

        _render_plan_details(
            plans[selected_index]
        )

    # ============================================
    # EDIT PREFERENCES
    # ============================================

    st.divider()

    if st.button(
        "← Edit trip preferences",
        use_container_width=True,
    ):

        st.session_state.screen = (
            "questionnaire"
        )

        st.session_state.step = 10

        st.rerun()
