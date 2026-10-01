"""Render a PDF only from an already structured, validated itinerary."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.travel.map_links import build_location_map_url, build_multi_stop_map_url
from app.travel.mobility import MobilityProfile
from app.travel.validation import TravelPlanValidator
from app.travel.plan_consistency import validate_plan_consistency
from app.travel.control_center import quality_indicators, trip_overview


class PDFReportError(ValueError):
    """Raised when a plan is not safe to turn into a user-facing report."""


def build_pdf_report(recommendation: dict[str, Any], preferences: dict[str, Any]) -> bytes:
    """Validate then render a PDF from structured itinerary data only."""
    _validate_for_pdf(recommendation)
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.4 * cm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TravelTitle", parent=styles["Title"], textColor=colors.HexColor("#07556e"), spaceAfter=10))
    styles.add(ParagraphStyle(name="TravelHeading", parent=styles["Heading2"], textColor=colors.HexColor("#07556e"), spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle(name="Timeline", parent=styles["BodyText"], leading=15, spaceAfter=5))
    story: list[Any] = []
    destination = recommendation.get("destination", {})
    city = destination.get("city") if isinstance(destination, dict) else preferences.get("destination")
    country = destination.get("country") if isinstance(destination, dict) else ""
    story.extend([Paragraph(f"AI Travel Plan: {_escape(str(city or 'Destination'))}", styles["TravelTitle"]), Paragraph("Generated from verified Geoapify places and clearly labelled planning estimates.", styles["BodyText"]), Spacer(1, 8)])
    accommodation = recommendation.get("selected_accommodation", {})
    overview = [["Destination", _escape(", ".join(str(value) for value in (city, country) if value) or "Unavailable")], ["Dates", _escape(_dates_label(recommendation))], ["Travellers", _escape(str(preferences.get("traveller_count", "Unavailable")))], ["Budget", _escape(str(preferences.get("custom_budget") or preferences.get("budget", "Unavailable")))], ["Travel style", _escape(str(preferences.get("travel_style", "Unavailable")))], ["Accommodation", _escape(str(accommodation.get("name", "Unavailable")))]]
    journey = recommendation.get("journey", {})
    if isinstance(journey, dict) and (journey.get("origin") or journey.get("requested_mode")):
        vehicle = f" ({journey['journey_vehicle']})" if journey.get("journey_vehicle") else ""
        overview.append(["Journey", _escape(f"{journey.get('origin') or 'Origin unavailable'} to {journey.get('destination') or 'Destination'} by {journey.get('requested_mode') or 'flexible mode'}{vehicle}")])
    table = Table(overview, colWidths=[3.4 * cm, 14 * cm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8f8fc")), ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#102a43")), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9e7ee")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("PADDING", (0, 0), (-1, -1), 6)]))
    story.extend([table, Spacer(1, 10)])
    control_overview = trip_overview(recommendation, preferences)
    priorities = ", ".join(str(value).replace("_", " ") for value in control_overview["priorities"]) or "No explicit priority"
    original_preferences = " · ".join(str(value) for value in control_overview["important_preferences"]) or "No additional natural-language preference"
    story.append(Paragraph("Trip overview", styles["TravelHeading"]))
    story.append(Paragraph(f"<b>Planning pace:</b> {_escape(str(control_overview['pace']).title())}. <b>Priorities:</b> {_escape(priorities)}.", styles["BodyText"]))
    story.append(Paragraph(f"<b>Original preferences:</b> {_escape(original_preferences)}.", styles["BodyText"]))
    if isinstance(journey, dict) and (journey.get("origin") or journey.get("requested_mode")):
        story.append(Paragraph("Getting there", styles["TravelHeading"]))
        for label, key in (("Outbound", "outbound"), ("Return", "return")):
            leg = journey.get(key, {})
            if not isinstance(leg, dict):
                continue
            parts = [str(leg.get("status", "unavailable"))]
            if isinstance(leg.get("distance_meters"), (int, float)):
                parts.append(f"{leg['distance_meters'] / 1000:.1f} km ORS road distance")
            if isinstance(leg.get("duration_minutes"), int):
                parts.append(f"{leg['duration_minutes']} min ORS car route")
            if isinstance(leg.get("fuel_cost_eur"), (int, float)):
                parts.append(f"EUR {leg['fuel_cost_eur']:.2f} calculated fuel")
            story.append(Paragraph(f"<b>{label}:</b> {_escape('; '.join(parts))}", styles["BodyText"]))
        story.append(Paragraph(_escape(str(journey.get("note", "Price data unavailable."))), styles["BodyText"]))
        mobility = recommendation.get("mobility_profile", {})
        if isinstance(mobility, dict):
            story.append(Paragraph(f"<b>Local mobility:</b> {_escape(str(mobility.get('preferred_transport') or 'not specified').replace('_', ' '))}", styles["BodyText"]))
    strategy = recommendation.get("trip_strategy")
    if isinstance(strategy, dict):
        priorities = ", ".join(str(value).replace("_", " ") for value in strategy.get("primary_concepts", [])) or "No explicit verified-category priority"
        story.append(Paragraph(f"<b>Trip strategy:</b> {_escape(str(strategy.get('pace', 'balanced')).title())} pace. Priorities: {_escape(priorities)}.", styles["BodyText"]))
    constraints = recommendation.get("trip_constraints")
    if isinstance(constraints, dict):
        from app.travel.constraints import TripConstraints
        understood = TripConstraints.from_dict(constraints).understood()
        if understood:
            story.append(Paragraph(f"<b>Trip constraints:</b> {_escape('; '.join(understood))}", styles["BodyText"]))
    for fit in recommendation.get("plan_fit", []):
        if isinstance(fit, dict):
            story.append(Paragraph(_escape(f"Plan fit — {fit.get('constraint', 'Constraint')}: {fit.get('status', 'unavailable to verify')}"), styles["BodyText"]))
    budget_summary = recommendation.get("budget_summary")
    if isinstance(budget_summary, dict):
        budget = budget_summary.get("budget", {})
        budget_text = ", ".join(
            value for value in (
                f"€{budget.get('total_eur'):g} total" if isinstance(budget.get("total_eur"), (int, float)) else "",
                f"€{budget.get('daily_eur'):g}/day" if isinstance(budget.get("daily_eur"), (int, float)) else "",
            ) if value
        ) or "No explicit budget"
        story.append(Paragraph(f"<b>Budget:</b> {_escape(budget_text)} — {_escape(str(budget_summary.get('status', 'price data unavailable')))}.", styles["BodyText"]))
        costs = budget_summary.get("verified_costs", {})
        calculated = budget_summary.get("calculated_costs", {})
        labels = {
            "transport_to_destination": "Getting there", "return_journey": "Return journey",
            "local_transport": "Local transport", "accommodation": "Accommodation",
            "food": "Food", "activities": "Activities",
        }
        for key, label in labels.items():
            verified = costs.get(key) if isinstance(costs, dict) else None
            estimated = calculated.get(key) if isinstance(calculated, dict) else None
            if isinstance(verified, (int, float)):
                value = f"EUR {verified:.2f} - verified provider price"
            elif isinstance(estimated, (int, float)):
                value = f"EUR {estimated:.2f} - calculated fuel estimate"
            else:
                value = "price unavailable"
            story.append(Paragraph(f"<b>{label}:</b> {_escape(value)}", styles["BodyText"]))
        subtotal = budget_summary.get("accounted_subtotal_eur")
        if isinstance(subtotal, (int, float)):
            story.append(Paragraph(f"<b>Known and calculated subtotal:</b> EUR {subtotal:.2f}. This is not a full trip total.", styles["BodyText"]))
        if isinstance(calculated, dict) and any(isinstance(value, (int, float)) for value in calculated.values()):
            story.append(Paragraph(_escape(str(budget_summary.get("calculation_note", ""))), styles["BodyText"]))
        unknown = budget_summary.get("unknown_categories", [])
        if isinstance(unknown, list) and unknown:
            story.append(Paragraph(f"<b>Unknown costs:</b> {_escape(', '.join(str(item) for item in unknown))}", styles["BodyText"]))
    story.append(Paragraph("Planning verification", styles["TravelHeading"]))
    for indicator in quality_indicators(recommendation):
        story.append(Paragraph(_escape(f"{indicator['label']}: {indicator['status']}"), styles["BodyText"]))
    if isinstance(accommodation, dict):
        _link_paragraph(story, "Accommodation map", build_location_map_url(accommodation), styles)
    for index, day in enumerate(recommendation.get("itinerary", [])):
        if not isinstance(day, dict):
            continue
        if index and index % 2 == 0:
            story.append(PageBreak())
        title = _escape(str(day.get("title") or f"Day {day.get('day', index + 1)}"))
        date_label = f" - {_escape(str(day['date']))}" if day.get("date") else ""
        story.append(Paragraph(f"Day {day.get('day', index + 1)}: {title}{date_label}", styles["TravelHeading"]))
        regional = day.get("regional_trip")
        if isinstance(regional, dict) and isinstance(regional.get("distance_from_accommodation_meters"), (int, float)):
            distance = regional["distance_from_accommodation_meters"] / 1000
            if regional.get("status") == "verified" and isinstance(regional.get("round_trip_distance_meters"), (int, float)):
                detail = f"Regional trip: {regional.get('anchor')} and {regional.get('companion')} (Geoapify places); ORS route to first stop {distance:.1f} km, round trip {regional['round_trip_distance_meters'] / 1000:.1f} km by {regional.get('transport_mode')}."
            else:
                detail = f"Regional trip: {regional.get('anchor')} and {regional.get('companion')} (Geoapify places); ORS car-road distance to first stop {distance:.1f} km. Motorcycle access and duration unverified."
            story.append(Paragraph(_escape(detail), styles["BodyText"]))
        if isinstance(day.get("strategy_explanation"), str):
            story.append(Paragraph(_escape(day["strategy_explanation"]), styles["BodyText"]))
        if day.get("travel_constraint_note"):
            story.append(Paragraph(_escape(str(day["travel_constraint_note"])), styles["BodyText"]))
        if day.get("mobility_warning"):
            story.append(Paragraph(_escape(str(day["mobility_warning"])), styles["BodyText"]))
        _link_paragraph(story, "Open full day route", build_multi_stop_map_url(day.get("route_stops", []), _day_transport_mode(day)), styles)
        for item in day.get("items", []):
            if not isinstance(item, dict):
                continue
            story.append(Paragraph(_item_text(item), styles["Timeline"]))
            if item.get("item_type") in {"activity", "accommodation"}:
                _link_paragraph(story, "View location", build_location_map_url(item), styles)
            if item.get("item_type") == "meal":
                for option in item.get("options", []):
                    if isinstance(option, dict):
                        detail = _escape(str(option.get("name", "Food option")))
                        if option.get("travel_time_data_status") == "verified":
                            detail += f" - {option.get('travel_duration_minutes')} min, {round(float(option.get('travel_distance_meters', 0)))} m (Verified ORS)"
                        else:
                            detail += " - route data unavailable"
                        story.append(Paragraph(f"Food option: {detail}", styles["BodyText"]))
                        _link_paragraph(story, "View food location", build_location_map_url(option), styles)
        story.append(Paragraph(_day_summary(day), styles["BodyText"]))
        return_route = day.get("return_route")
        if isinstance(return_route, dict) and return_route.get("data_status") == "verified" and isinstance(return_route.get("distance_meters"), (int, float)):
            story.append(Paragraph(_escape(f"Return to accommodation: {float(return_route['distance_meters']) / 1000:.1f} km, {return_route['duration_minutes']} min by ORS {return_route.get('transport_mode', 'road')} profile; departure time not assigned."), styles["BodyText"]))
    document.build(story)
    return buffer.getvalue()


def _validate_for_pdf(recommendation: dict[str, Any]) -> None:
    context = recommendation.get("validation_context") if isinstance(recommendation, dict) else None
    if not isinstance(context, dict):
        raise PDFReportError("This itinerary has no validation context and cannot be exported.")
    try:
        validate_plan_consistency(recommendation)
        TravelPlanValidator().validate(recommendation, context["travel_data"], int(context["duration_days"]), MobilityProfile.from_dict(context.get("mobility_profile", {})))
    except Exception as error:
        raise PDFReportError(f"The itinerary is invalid and cannot be exported: {error}") from error


def _item_text(item: dict[str, Any]) -> str:
    period = " - ".join(value for value in (item.get("start_time"), item.get("end_time")) if isinstance(value, str))
    prefix = f"<b>{_escape(period)}</b> " if period else ""
    if item.get("item_type") == "travel":
        if item.get("travel_time_data_status") == "verified":
            return prefix + f"Travel by {_escape(str(item.get('transport_mode') or 'route'))}: {_escape(str(item.get('travel_duration_minutes')))} min, {_escape(str(item.get('travel_distance_meters')))} m - Verified by OpenRouteService."
        return prefix + f"Travel: {_escape(str(item.get('planning_buffer_minutes', '')))} min planning buffer - estimated; route data unavailable."
    if item.get("item_type") == "meal":
        status = "real Geoapify options" if item.get("options") else "food options unavailable"
        return prefix + f"{_escape(str(item.get('meal_type', 'Meal')).title())}: 60 min planning allowance - estimated; {status}."
    if item.get("item_type") == "free_time":
        return prefix + f"Free time: {_escape(str(item.get('duration_minutes', '')))} min."
    if item.get("item_type") == "accommodation":
        return prefix + f"Accommodation: {_escape(str(item.get('name', 'Accommodation')))}."
    status = "Verified" if item.get("duration_data_status") == "verified" else "Estimated planning duration"
    return prefix + f"Activity: <b>{_escape(str(item.get('name', 'Activity')))}</b> - {_escape(str(item.get('duration_minutes', '')))} min ({status})."


def _day_summary(day: dict[str, Any]) -> str:
    activities = [item for item in day.get("items", []) if isinstance(item, dict) and item.get("item_type") == "activity"]
    travel = [item for item in day.get("items", []) if isinstance(item, dict) and item.get("item_type") == "travel" and item.get("travel_time_data_status") == "verified"]
    meals = [item for item in day.get("meals", []) if isinstance(item, dict)]
    return (f"<b>Day summary:</b> {len(activities)} activities; {sum(int(item.get('duration_minutes', 0)) for item in activities)} min planned activity time; {sum(int(item.get('travel_duration_minutes', 0)) for item in travel)} min verified travel; {sum(float(item.get('travel_distance_meters', 0)) for item in travel):.0f} m verified distance; {sum(len(item.get('options', [])) for item in meals)} food options.")


def _day_transport_mode(day: dict[str, Any]) -> str | None:
    for item in day.get("items", []):
        if isinstance(item, dict) and item.get("item_type") == "travel" and isinstance(item.get("transport_mode"), str):
            return item["transport_mode"]
    return None


def _dates_label(recommendation: dict[str, Any]) -> str:
    dates = [day.get("date") for day in recommendation.get("itinerary", []) if isinstance(day, dict) and day.get("date")]
    return f"{dates[0]} to {dates[-1]}" if dates else "Dates not specified"


def _link_paragraph(story: list[Any], label: str, url: str | None, styles: Any) -> None:
    if url:
        story.append(Paragraph(f'<link href="{_escape(url)}" color="#087ea4">{_escape(label)}</link>', styles["BodyText"]))


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
