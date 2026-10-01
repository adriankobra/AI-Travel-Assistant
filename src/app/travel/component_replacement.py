"""Transactional replacements within an already validated real travel plan."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.ai.intent_analyzer import IntentPreference
from app.travel.daily_planning import DailyPlanner
from app.travel.food_planning import FoodPlanner
from app.travel.itinerary import place_snapshot
from app.travel.mobility import MobilityProfile
from app.travel.place_ranking import rank_places
from app.travel.plan_consistency import validate_plan_consistency
from app.travel.routing import RoutingService
from app.travel.validation import TravelPlanValidator
from app.travel.constraints import TripConstraints, assess_plan_fit
from app.travel.budget import TripBudget, budget_summary, prefer_affordable
from app.travel.transport_planning import build_journey
from app.travel.regional_planning import refresh_regional_explanations


class ComponentReplacementError(ValueError):
    pass


def _context(plan: dict[str, Any]) -> tuple[dict[str, Any], int, MobilityProfile, list[IntentPreference]]:
    context = plan.get("validation_context")
    if not isinstance(context, dict) or not isinstance(context.get("travel_data"), dict):
        raise ComponentReplacementError("The current plan has no verified replacement context.")
    raw_intents = plan.get("intent", [])
    intents = [IntentPreference(str(item["concept"]), str(item["strength"]), str(item["polarity"])) for item in raw_intents if isinstance(item, dict) and {"concept", "strength", "polarity"}.issubset(item)]
    return context["travel_data"], int(context["duration_days"]), MobilityProfile.from_dict(context.get("mobility_profile", {})), intents


def _validate(candidate: dict[str, Any], data: dict[str, Any], duration: int, mobility: MobilityProfile) -> dict[str, Any]:
    TravelPlanValidator().validate(candidate, data, duration, mobility)
    validate_plan_consistency(candidate)
    return candidate


def _activity_names(days: list[dict[str, Any]]) -> set[str]:
    return {
        str(activity.get("name")).casefold()
        for day in days if isinstance(day, dict)
        for activity in day.get("activities", []) if isinstance(activity, dict) and isinstance(activity.get("name"), str)
    }


def _similar_preference_candidates(
    ranked: list[Any], current_name: object, excluded_names: set[str],
) -> list[Any]:
    """Prefer a different candidate with the same verified intent evidence.

    This keeps replacement generic: it operates on ranking evidence emitted by
    the intent system rather than naming special experiences such as spa.
    """
    current = next(
        (item for item in ranked if str(item.place.get("name", "")).casefold() == str(current_name or "").casefold()),
        None,
    )
    eligible = [
        item for item in ranked
        if isinstance(item.place.get("name"), str)
        and item.place["name"].casefold() not in excluded_names
        and not item.has_strong_negative_conflict
    ]
    if current is None or not current.matched_concepts:
        return eligible
    similar = [item for item in eligible if set(current.matched_concepts).intersection(item.matched_concepts)]
    return similar or eligible


def _rebuild_days(
    candidate: dict[str, Any], data: dict[str, Any], intents: list[IntentPreference],
    mobility: MobilityProfile, preferences: dict[str, Any], routing: RoutingService,
    days: list[dict[str, Any]],
) -> None:
    """Recreate all derived schedule/map/meal fields before validation."""
    expected = _activity_names(days)
    DailyPlanner(routing).plan(
        days, data.get("activities", []), intents, preferences,
        candidate.get("destination", {}), mobility, candidate.get("selected_accommodation"),
        constraints=TripConstraints.from_dict(candidate.get("trip_constraints")),
    )
    if _activity_names(days) != expected:
        raise ComponentReplacementError("The edit would make the day exceed its realistic schedule.")
    FoodPlanner(routing).attach_options(
        candidate.get("itinerary", []), data.get("food_options", []), intents,
        mobility, candidate.get("selected_accommodation"),
        budget=TripBudget.from_dict(candidate.get("trip_budget")),
    )
    candidate["plan_fit"] = assess_plan_fit(candidate, TripConstraints.from_dict(candidate.get("trip_constraints")))
    refresh_regional_explanations(candidate)
    old_journey = candidate.get("journey", {})
    candidate["journey"] = build_journey(
        preferences, candidate.get("destination", {}), candidate.get("selected_accommodation"), routing,
        origin_place=old_journey.get("origin_place") if isinstance(old_journey, dict) else None,
    )
    candidate["budget_summary"] = budget_summary(candidate, TripBudget.from_dict(candidate.get("trip_budget")))


def replace_activity(plan: dict[str, Any], day_number: int, activity_name: str, preferences: dict[str, Any], routing: RoutingService) -> dict[str, Any]:
    """Return a new plan with one real activity replaced, or raise unchanged."""
    candidate = deepcopy(plan)
    data, duration, mobility, intents = _context(candidate)
    used = {item.get("name", "").casefold() for day in candidate.get("itinerary", []) if isinstance(day, dict) for item in day.get("activities", []) if isinstance(item, dict)}
    ranked = rank_places(data.get("activities", []), intents, mobility)
    # Discovery intentionally retains meals for FoodPlanner, but a café or
    # restaurant must not replace an itinerary activity when a real
    # experience is available.  Preserve a factual fallback for sparse areas.
    non_food_ranked = [item for item in ranked if not FoodPlanner._is_food_place(item.place)]
    primary_ranked = non_food_ranked or ranked
    budget = TripBudget.from_dict(candidate.get("trip_budget"))
    ranked_choices = _similar_preference_candidates(primary_ranked, activity_name, used)
    affordable = prefer_affordable([item.place for item in ranked_choices], budget)
    replacement = next((item for item in affordable if isinstance(item.get("name"), str)), None)
    if replacement is None:
        raise ComponentReplacementError("No different verified activity is available for this plan.")
    day = next((item for item in candidate.get("itinerary", []) if isinstance(item, dict) and item.get("day") == day_number), None)
    if not isinstance(day, dict):
        raise ComponentReplacementError("The selected itinerary day no longer exists.")
    changed = False
    for activity in day.get("activities", []):
        if isinstance(activity, dict) and activity.get("name") == activity_name:
            activity.update({"name": replacement["name"], "address": str(replacement.get("address", "")), "reason": ""})
            changed = True
            break
    if not changed:
        raise ComponentReplacementError("The selected activity no longer exists.")
    _rebuild_days(candidate, data, intents, mobility, preferences, routing, [day])
    return _validate(candidate, data, duration, mobility)


def move_activity(
    plan: dict[str, Any], activity_name: str, source_day_number: int,
    target_day_number: int, preferences: dict[str, Any], routing: RoutingService,
) -> dict[str, Any]:
    """Move one verified activity and transactionally rebuild both affected days."""
    if source_day_number == target_day_number:
        raise ComponentReplacementError("Choose a different day for this activity.")
    candidate = deepcopy(plan)
    data, duration, mobility, intents = _context(candidate)
    source = next((day for day in candidate.get("itinerary", []) if isinstance(day, dict) and day.get("day") == source_day_number), None)
    target = next((day for day in candidate.get("itinerary", []) if isinstance(day, dict) and day.get("day") == target_day_number), None)
    if not isinstance(source, dict) or not isinstance(target, dict):
        raise ComponentReplacementError("The selected itinerary day no longer exists.")
    activities = source.get("activities", [])
    if not isinstance(activities, list) or len(activities) <= 1:
        raise ComponentReplacementError("Each day needs at least one verified activity; this activity cannot be moved.")
    index = next((i for i, item in enumerate(activities) if isinstance(item, dict) and item.get("name") == activity_name), None)
    if index is None:
        raise ComponentReplacementError("The selected activity no longer exists.")
    moved = activities.pop(index)
    target.setdefault("activities", []).append(moved)
    _rebuild_days(candidate, data, intents, mobility, preferences, routing, [source, target])
    return _validate(candidate, data, duration, mobility)


def remove_activity(
    plan: dict[str, Any], day_number: int, activity_name: str,
    preferences: dict[str, Any], routing: RoutingService,
) -> dict[str, Any]:
    """Remove one activity while preserving a valid, rescheduled day."""
    candidate = deepcopy(plan)
    data, duration, mobility, intents = _context(candidate)
    day = next((item for item in candidate.get("itinerary", []) if isinstance(item, dict) and item.get("day") == day_number), None)
    if not isinstance(day, dict):
        raise ComponentReplacementError("The selected itinerary day no longer exists.")
    activities = day.get("activities", [])
    if not isinstance(activities, list) or len(activities) <= 1:
        raise ComponentReplacementError("Each day needs at least one verified activity; this activity cannot be removed.")
    kept = [item for item in activities if not (isinstance(item, dict) and item.get("name") == activity_name)]
    if len(kept) == len(activities):
        raise ComponentReplacementError("The selected activity no longer exists.")
    day["activities"] = kept
    _rebuild_days(candidate, data, intents, mobility, preferences, routing, [day])
    return _validate(candidate, data, duration, mobility)


def replace_hotel(plan: dict[str, Any], preferences: dict[str, Any], routing: RoutingService) -> dict[str, Any]:
    """Replace accommodation and rebuild every derived day around its new base."""
    candidate = deepcopy(plan)
    data, duration, mobility, intents = _context(candidate)
    current = candidate.get("selected_accommodation", {}).get("name") if isinstance(candidate.get("selected_accommodation"), dict) else None
    ranked = rank_places(data.get("accommodations", []), intents, mobility)
    budget = TripBudget.from_dict(candidate.get("trip_budget"))
    ranked_choices = _similar_preference_candidates(ranked, current, {str(current or "").casefold()})
    replacement = next((item for item in prefer_affordable([ranked_item.place for ranked_item in ranked_choices], budget, nights=duration) if isinstance(item.get("name"), str)), None)
    if replacement is None:
        raise ComponentReplacementError("No different verified accommodation is available for this plan.")
    candidate["selected_accommodation"] = {**place_snapshot(replacement), "reason": ""}
    days = [day for day in candidate.get("itinerary", []) if isinstance(day, dict)]
    _rebuild_days(candidate, data, intents, mobility, preferences, routing, days)
    return _validate(candidate, data, duration, mobility)


def replace_food(plan: dict[str, Any], day_number: int, meal_type: str, preferences: dict[str, Any], routing: RoutingService) -> dict[str, Any]:
    """Replace the first displayed food alternative with another verified place."""
    candidate = deepcopy(plan)
    data, duration, mobility, intents = _context(candidate)
    day = next((item for item in candidate.get("itinerary", []) if isinstance(item, dict) and item.get("day") == day_number), None)
    if not isinstance(day, dict):
        raise ComponentReplacementError("The selected itinerary day no longer exists.")
    meal = next((item for item in day.get("meals", []) if isinstance(item, dict) and item.get("meal_type") == meal_type), None)
    if not isinstance(meal, dict) or not meal.get("options"):
        raise ComponentReplacementError("No verified food option is available to replace.")
    current = meal["options"][0].get("name")
    used = {str(option.get("name", "")).casefold() for d in candidate.get("itinerary", []) if isinstance(d, dict) for m in d.get("meals", []) if isinstance(m, dict) for option in m.get("options", []) if isinstance(option, dict)}
    anchor = meal.get("anchor") or (day.get("activities") or [candidate.get("selected_accommodation")])[0]
    ranked = rank_places(data.get("food_options", []), intents, mobility)
    budget = TripBudget.from_dict(candidate.get("trip_budget"))
    ranked_choices = _similar_preference_candidates(ranked, current, used)
    budget_ordered = prefer_affordable([ranked_item.place for ranked_item in ranked_choices], budget)
    choices = [item for item in budget_ordered if isinstance(item.get("name"), str)]
    if not choices:
        # A small destination can legitimately exhaust the no-repeat meal pool.
        # Reuse another factual option rather than claiming there are none.
        fallback_ranked = _similar_preference_candidates(
            ranked, current, {str(current or "").casefold()}
        )
        choices = prefer_affordable([item.place for item in fallback_ranked], budget)
    if not choices:
        raise ComponentReplacementError("No different verified food option is available.")
    replacement = place_snapshot(choices[0])
    route = routing.route(anchor, choices[0], mobility.planning_mode() or "walking") if isinstance(anchor, dict) else None
    replacement.update({"source": "Geoapify", "route_from_anchor": route.to_dict() if route else None, "travel_time_data_status": route.data_status if route else "unavailable", "travel_duration_minutes": route.duration_minutes if route and route.data_status == "verified" else None, "travel_distance_meters": route.distance_meters if route and route.data_status == "verified" else None, "transport_mode": route.transport_mode if route else None})
    meal["options"][0] = replacement
    for item in day.get("items", []):
        if isinstance(item, dict) and item.get("item_type") == "meal" and item.get("meal_type") == meal_type:
            item["options"] = meal["options"]
    candidate["budget_summary"] = budget_summary(candidate, TripBudget.from_dict(candidate.get("trip_budget")))
    return _validate(candidate, data, duration, mobility)
