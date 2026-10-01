"""Factual read models for the interactive trip Control Center."""

from __future__ import annotations

from typing import Any

from app.travel.spatial_diversity import spatial_cluster


def trip_overview(plan: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    destination = plan.get("destination", {})
    hotel = plan.get("selected_accommodation", {})
    strategy = plan.get("trip_strategy", {})
    mobility = plan.get("mobility_profile", {})
    journey = plan.get("journey", {})
    days = [day for day in plan.get("itinerary", []) if isinstance(day, dict)]
    important = [value for value in (preferences.get("notes"), preferences.get("additional_preferences")) if value]
    return {
        "destination": ", ".join(str(destination.get(key)) for key in ("city", "country") if isinstance(destination, dict) and destination.get(key)) or "Unavailable",
        "hotel": hotel.get("name", "Unavailable") if isinstance(hotel, dict) else "Unavailable",
        "days": len(days),
        "dates": [day.get("date") for day in days if day.get("date")],
        "travel_style": preferences.get("travel_style") or "Not specified",
        "pace": strategy.get("pace", "balanced") if isinstance(strategy, dict) else "balanced",
        "mobility": mobility if isinstance(mobility, dict) else {},
        "important_preferences": important,
        "priorities": strategy.get("primary_concepts", []) if isinstance(strategy, dict) else [],
        "avoidances": strategy.get("avoided_concepts", []) if isinstance(strategy, dict) else [],
        "journey": journey if isinstance(journey, dict) else {},
    }


def place_explanation(plan: dict[str, Any], place: dict[str, Any], kind: str) -> list[str]:
    """Return only explanation fragments backed by stored ranking/plan data."""
    selected = plan.get("selected_place_ranking", {})
    evidence: dict[str, Any] | None = None
    if isinstance(selected, dict):
        if kind == "accommodation":
            value = selected.get("accommodation")
            evidence = value if isinstance(value, dict) else None
        elif kind == "food":
            name = place.get("name")
            evidence = next((item for item in selected.get("food", []) if isinstance(item, dict) and item.get("name") == name), None)
        else:
            name = place.get("name")
            evidence = next((item for item in selected.get("activities", []) if isinstance(item, dict) and item.get("name") == name), None)
    output: list[str] = []
    if isinstance(evidence, dict):
        concepts = evidence.get("matched_concepts", [])
        if concepts:
            output.append("Verified category match: " + ", ".join(str(value).replace("_", " ") for value in concepts) + ".")
        if isinstance(evidence.get("mobility_score"), (int, float)) and evidence["mobility_score"] > 0:
            output.append("Compatible with the stored mobility profile.")
    categories = place.get("categories", [])
    if isinstance(categories, list) and categories:
        output.append("Verified place categories: " + ", ".join(str(value) for value in categories[:3]) + ".")
    budget = plan.get("budget_summary", {})
    if isinstance(budget, dict) and budget.get("status") == "within verified budget data":
        output.append("Fits the available verified budget records.")
    return output or ["Included from verified provider place data; no additional match evidence is available."]


def preference_influence(plan: dict[str, Any]) -> list[str]:
    """Human-readable, evidence-only proof that preferences shaped this plan."""
    selected = plan.get("selected_place_ranking", {})
    activities = selected.get("activities", []) if isinstance(selected, dict) else []
    food = selected.get("food", []) if isinstance(selected, dict) else []
    accommodation = selected.get("accommodation") if isinstance(selected, dict) else None
    evidence = [item for item in [*activities, *food] if isinstance(item, dict)]
    if isinstance(accommodation, dict):
        evidence.append(accommodation)
    result: list[str] = []
    for intent in plan.get("intent", []):
        if not isinstance(intent, dict) or not isinstance(intent.get("concept"), str):
            continue
        concept = intent["concept"]
        label = concept.replace("_", " ").title()
        matches = [str(item.get("name")) for item in evidence if concept in item.get("matched_concepts", []) and item.get("name")]
        if intent.get("polarity") == "positive" and matches:
            result.append(f"{label} → verified category match: {', '.join(list(dict.fromkeys(matches))[:2])}.")
        elif intent.get("polarity") == "negative" and not matches:
            result.append(f"Avoid {label} → no selected activity has that verified category.")
    strategy = plan.get("trip_strategy", {})
    free_minutes = sum(
        int(day.get("schedule", {}).get("free_time_minutes", 0) or 0)
        for day in plan.get("itinerary", []) if isinstance(day, dict) and isinstance(day.get("schedule"), dict)
    )
    if isinstance(strategy, dict) and strategy.get("pace") == "relaxed" and free_minutes:
        result.append(f"Relaxed pace → {free_minutes} minutes of scheduled free time retained.")
    return result


def quality_indicators(plan: dict[str, Any]) -> list[dict[str, str]]:
    """Compact statuses, deliberately not a synthetic quality score."""
    selected = plan.get("selected_place_ranking", {})
    activities = selected.get("activities", []) if isinstance(selected, dict) else []
    matched = any(isinstance(item, dict) and item.get("matched_concepts") for item in activities)
    unmet = plan.get("unverified_activity_preference_concepts", [])
    preference = "partially matched" if matched and unmet else "matched using verified categories" if matched else "unavailable to verify"
    fit = plan.get("plan_fit", [])
    statuses = [item.get("status") for item in fit if isinstance(item, dict)]
    constraint = "partially satisfied" if "partially satisfied" in statuses else "unavailable to verify" if "unavailable to verify" in statuses else "satisfied" if statuses else "no explicit constraints"
    budget = plan.get("budget_summary", {})
    budget_status = str(budget.get("status", "price data unavailable")) if isinstance(budget, dict) else "price data unavailable"
    items = [item for day in plan.get("itinerary", []) if isinstance(day, dict) for item in day.get("items", []) if isinstance(item, dict)]
    travel = [item for item in items if item.get("item_type") == "travel"]
    route = "verified routes available" if travel and all(item.get("travel_time_data_status") == "verified" for item in travel) else "partially verified" if any(item.get("travel_time_data_status") == "verified" for item in travel) else "route data unavailable"
    meals = [item for item in items if item.get("item_type") == "meal"]
    food = "food options available" if meals and all(item.get("options") for item in meals) else "some food options unavailable" if meals else "food data unavailable"
    places = [activity for day in plan.get("itinerary", []) if isinstance(day, dict) for activity in day.get("activities", []) if isinstance(activity, dict)]
    clusters = {spatial_cluster(place, places) for place in places}
    diversity = "multiple verified areas" if len(clusters - {None}) > 1 else "limited verified area diversity" if places else "unavailable to verify"
    complete = sum(1 for place in places if place.get("name") and place.get("address") and place.get("latitude") is not None and place.get("longitude") is not None)
    completeness = "complete provider identity and coordinates" if places and complete == len(places) else "partial provider data"
    mobility = plan.get("mobility_profile", {})
    mobility_status = "stored mobility profile applied" if isinstance(mobility, dict) and any(value is not None for value in mobility.values()) else "mobility preference unavailable"
    return [
        {"label": "Preference fit", "status": preference},
        {"label": "Constraint fit", "status": constraint},
        {"label": "Budget verification", "status": budget_status},
        {"label": "Mobility compatibility", "status": mobility_status},
        {"label": "Route verification", "status": route},
        {"label": "Food availability", "status": food},
        {"label": "Spatial diversity", "status": diversity},
        {"label": "Data completeness", "status": completeness},
    ]
