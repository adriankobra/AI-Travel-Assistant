import json

from app.ai.groq_client import GroqClient
from app.ai.intent_analyzer import IntentAnalyzer, IntentPreference
from app.ai.mobility_analyzer import MobilityAnalyzer
from app.travel.mobility import MobilityProfile
from app.travel.place_ranking import rank_places, unmatched_positive_concepts
from app.travel.daily_planning import DailyPlanner
from app.travel.food_planning import FoodPlanner
from app.travel.routing import RoutingService
from app.travel.routing_openrouteservice import OpenRouteServiceRoutingService
from app.travel.validation import TravelPlanValidator
from app.travel.spatial_diversity import diversify, spatial_cluster
from app.travel.trip_strategy import TripStrategy
from app.travel.constraints import TripConstraints, assess_plan_fit
from app.travel.budget import TripBudget, budget_summary, prefer_affordable
from app.travel.transport_planning import build_journey
from app.travel.regional_planning import promote_regional_day, fill_sparse_days, keep_selected_places_mobility_compatible, refresh_regional_explanations


TRAVEL_RECOMMENDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_accommodation": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string"
                },
                "address": {
                    "type": "string"
                },
                "reason": {
                    "type": "string"
                }
            },
            "required": [
                "name",
                "address",
                "reason"
            ],
            "additionalProperties": False
        },
        "itinerary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day": {
                        "type": "integer"
                    },
                    "title": {
                        "type": "string"
                    },
                    "activities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string"
                                },
                                "address": {
                                    "type": "string"
                                },
                                "reason": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "name",
                                "address",
                                "reason"
                            ],
                            "additionalProperties": False
                        }
                    }
                },
                "required": [
                    "day",
                    "title",
                    "activities"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": [
        "selected_accommodation",
        "itinerary"
    ],
    "additionalProperties": False
}


class TravelRecommender:

    def __init__(
        self,
        client: GroqClient | None = None,
        intent_analyzer: IntentAnalyzer | None = None,
        mobility_analyzer: MobilityAnalyzer | None = None,
        routing_service: RoutingService | None = None,
    ) -> None:
        self.client = client or GroqClient()
        self.intent_analyzer = intent_analyzer or IntentAnalyzer(self.client)
        self.mobility_analyzer = mobility_analyzer or MobilityAnalyzer(self.client)
        self.validator = TravelPlanValidator()
        route_service = routing_service or OpenRouteServiceRoutingService()
        self.routing_service = route_service
        self.daily_planner = DailyPlanner(route_service)
        self.food_planner = FoodPlanner(route_service)

    def recommend(
        self,
        preferences: dict,
        destination: dict,
        travel_data: dict,
        duration_days: int,
        excluded_accommodation_names: set[str] | None = None,
        excluded_activity_names: set[str] | None = None,
    ) -> dict:

        intents = self.intent_analyzer.analyze(preferences)
        strategy = TripStrategy.from_intents(intents)
        constraints = TripConstraints.from_preferences(preferences)
        budget = TripBudget.from_preferences(preferences)
        mobility = self._analyze_mobility(preferences)
        ranked_accommodations = rank_places(
            travel_data.get("accommodations", []), intents, mobility
        )
        ranked_activities = rank_places(
            travel_data.get("activities", []), intents, mobility
        )
        ranked_food = rank_places(
            travel_data.get("food_options", []), intents, mobility
        )
        # Geoapify discovery deliberately includes cafes and restaurants so that
        # the food planner can offer real meal choices.  They are not, however,
        # interchangeable with a primary trip activity.  Keep meal-only places
        # out of the itinerary prompt whenever there are factual non-food
        # alternatives; FoodPlanner receives the separate food pool below.
        primary_ranked_activities = self._primary_activity_ranking(ranked_activities)
        accommodation_match_gaps = unmatched_positive_concepts(intents, ranked_accommodations)
        activity_match_gaps = unmatched_positive_concepts(intents, ranked_activities)

        # Keep only sorted, factual Geoapify data in the LLM prompt.  Validator still
        # receives the original data and remains the source of truth for verification.
        excluded_accommodation_names = {name.casefold() for name in (excluded_accommodation_names or set())}
        excluded_activity_names = {name.casefold() for name in (excluded_activity_names or set())}
        selectable_ranked_activities = [item for item in primary_ranked_activities if str(item.place.get("name", "")).casefold() not in excluded_activity_names]
        accommodations = diversify(prefer_affordable(
            [item.place for item in ranked_accommodations if item.place.get("name", "").casefold() not in excluded_accommodation_names], budget, nights=duration_days
        ))
        activities = diversify(prefer_affordable(
            [item.place for item in primary_ranked_activities if item.place.get("name", "").casefold() not in excluded_activity_names], budget
        ))
        llm_accommodations = [self._llm_place_data(item) for item in accommodations]
        llm_activities = [self._llm_place_data(item) for item in activities]

        accommodation_names = [
            item["name"]
            for item in accommodations
            if item.get("name")
        ]

        activity_names = [
            item["name"]
            for item in activities
            if item.get("name")
        ]

        if not accommodation_names:
            raise ValueError(
                "No real accommodations were found "
                "for this destination."
            )

        if not activity_names:
            raise ValueError(
                "No real activities were found "
                "for this destination."
            )

        prompt = (
            "Create a practical travel itinerary using ONLY "
            "the real places provided below.\n\n"

            "IMPORTANT ACCOMMODATION RULE:\n"
            "Select the accommodation only from the "
            "AVAILABLE ACCOMMODATIONS list.\n"
            "Copy its name exactly.\n"
            "Do not invent or modify the accommodation name.\n\n"

            "IMPORTANT ACTIVITY RULE:\n"
            "Select activities only from the "
            "AVAILABLE ACTIVITIES list.\n"
            "Copy each activity name exactly.\n"
            "Do not invent or modify activity names.\n\n"

            "IMPORTANT REASON RULE:\n"
            "The reason explains why the AI selected the place "
            "for this traveler.\n"
            "Do NOT invent factual information about the place.\n"
            "Do NOT claim that a hotel has comfortable rooms, "
            "excellent service, free parking, cheap prices, "
            "good reviews, or other features unless that "
            "information is explicitly provided in the input data.\n"
            "Do NOT invent opening hours, prices, ratings, "
            "availability, facilities or services.\n"
            "Keep reasons short and based on the traveler's preferences.\n\n"

            "ITINERARY RULES:\n"
            f"- Create exactly {duration_days} days.\n"
            "- Choose a small, realistic set of activities for each day; the number "
            "may differ by day and must not be fixed.\n"
            "- Do not invent visit durations, opening hours, prices, or route travel times. "
            "A separate planner will add clearly labelled conservative estimates.\n"
            "- Day numbers must be integers: 1, 2, 3, etc.\n"
            "- A maximum of ONE monument or memorial is allowed "
            "per day.\n"
            "- NEVER use the same activity more than once "
            "throughout the entire itinerary.\n"
            "- Try to create variety within each day.\n"
            "- When real suitable places span multiple geographic areas, spread days across those areas instead of repeatedly selecting one tiny cluster.\n"
            "- If a strong positive intent has verified matching places, include at least one matching experience; do not invent one when there is no match.\n"
            "- Consider the traveler's preferences.\n"
            "- Organize activities logically when possible.\n\n"

            "MOBILITY PROFILE (not a place fact):\n"
            f"{json.dumps(mobility.to_dict(), ensure_ascii=False)}\n"
            "- Do not select a car-rental place when rental_car_allowed is false.\n"
            "- For walking-only profiles, prefer only places with compatible verified distance data.\n\n"

            "AVAILABLE ACCOMMODATIONS:\n"
            f"{json.dumps(accommodation_names, ensure_ascii=False)}\n\n"

            "AVAILABLE ACTIVITIES:\n"
            f"{json.dumps(activity_names, ensure_ascii=False)}\n\n"

            "TRAVELER PREFERENCES:\n"
            f"{json.dumps(preferences, ensure_ascii=False, default=str)}\n\n"

            "INTERPRETED USER INTENT (not place facts):\n"
            f"{json.dumps([intent.to_dict() for intent in intents], ensure_ascii=False)}\n\n"

            "DESTINATION:\n"
            f"{json.dumps(destination, ensure_ascii=False, default=str)}\n\n"

            "VERIFIED ACCOMMODATION DATA:\n"
            f"{json.dumps(llm_accommodations, ensure_ascii=False, default=str)}\n\n"

            "VERIFIED ACTIVITY DATA:\n"
            f"{json.dumps(llm_activities, ensure_ascii=False, default=str)}"
        )

        response = self.client.send_structured_prompt(
            prompt,
            system_prompt=(
                "You are a practical AI travel planner. "
                "Use ONLY the provided real places. "
                "Never invent places or factual information. "
                "Accommodation and activity names must come "
                "from the provided lists. "
                "Reasons must explain the AI's selection based "
                "on traveler preferences, not invent facts. "
                "Never put more than one monument or memorial "
                "on the same day. "
                "Never use the same activity more than once "
                "in the entire itinerary."
            ),
            response_schema=TRAVEL_RECOMMENDATION_SCHEMA,
        )

        # The provider-backed selection is authoritative.  It must happen
        # before scheduling: otherwise the schedule, route stops and map could
        # retain the LLM's hotel while the visible plan shows another one.
        selected = self._select_accommodation(accommodations, preferences, destination)
        if selected is not None:
            response["selected_accommodation"] = {
                "name": selected["name"], "address": str(selected.get("address", "")), "reason": "",
                **{key: selected[key] for key in ("latitude", "longitude", "categories", "city", "country", "place_id") if key in selected},
            }

        # The LLM is constrained to real places, but selection remains a
        # suggestion.  Apply deterministic preference guards before creating
        # any derived schedule, map or PDF fields.
        self._remove_strong_negative_conflicts(response, selectable_ranked_activities)
        # Reserve a verified strong intent before timeline construction so the
        # daily planner, map and PDF all receive the same activity list.
        self._ensure_strong_verified_experience(response, selectable_ranked_activities, intents)
        keep_selected_places_mobility_compatible(response.get("itinerary", []), selectable_ranked_activities, selected, mobility)
        self._ensure_regional_day(response, selectable_ranked_activities, intents, mobility, selected, constraints, excluded_activity_names)
        self._improve_spatial_diversity(response, selectable_ranked_activities, intents, mobility, selected, self.routing_service, constraints)
        fill_sparse_days(response.get("itinerary", []), selectable_ranked_activities, constraints, strategy, self.routing_service, mobility)

        self.daily_planner.plan(
            itinerary=response.get("itinerary", []),
            real_activities=travel_data.get("activities", []),
            intents=intents,
            preferences=preferences,
            destination=destination,
            mobility_profile=mobility,
            accommodation=response.get("selected_accommodation"),
            constraints=constraints,
        )

        self.validator.validate(
            response=response,
            travel_data=travel_data,
            duration_days=duration_days,
            mobility_profile=mobility,
        )
        refresh_regional_explanations(response)
        self._replace_reasons_with_verified_matches(
            response, ranked_accommodations, ranked_activities
        )
        self.food_planner.attach_options(
            response.get("itinerary", []),
            travel_data.get("food_options", []),
            intents,
            mobility,
            response.get("selected_accommodation"),
            budget=budget,
        )
        # Food options and the structured timeline are still provider-backed
        # data, so validate again after they are attached.
        self.validator.validate(
            response=response,
            travel_data=travel_data,
            duration_days=duration_days,
            mobility_profile=mobility,
        )

        self._attach_strategy_explanations(response, ranked_activities, strategy)

        # Metadata for later UI phases. It does not claim that a missing service exists.
        response["intent"] = [intent.to_dict() for intent in intents]
        response["trip_strategy"] = strategy.to_dict()
        response["trip_constraints"] = constraints.to_dict()
        response["plan_fit"] = assess_plan_fit(response, constraints)
        response["trip_budget"] = budget.to_dict()
        response["journey"] = build_journey(
            preferences, destination, response.get("selected_accommodation"), self.routing_service
        )
        response["budget_summary"] = budget_summary(response, budget)
        response["mobility_profile"] = mobility.to_dict()
        response["unverified_accommodation_preference_concepts"] = accommodation_match_gaps
        response["unverified_activity_preference_concepts"] = activity_match_gaps
        response["selected_place_ranking"] = self._selected_place_ranking(
            response, ranked_accommodations, ranked_activities, ranked_food
        )
        response["accommodation_candidates"] = [self._llm_place_data(item) for item in accommodations[:8]]
        response["validation_context"] = {
            "travel_data": travel_data,
            "duration_days": duration_days,
            "mobility_profile": mobility.to_dict(),
            "trip_constraints": constraints.to_dict(),
            "trip_budget": budget.to_dict(),
        }
        response["destination"] = destination
        return response

    @staticmethod
    def _attach_strategy_explanations(response: dict, ranked_activities: list, strategy: TripStrategy) -> None:
        """Attach transparent day purpose explanations from ranking evidence."""
        matches_by_name = {item.place.get("name", "").casefold(): item.matched_concepts for item in ranked_activities}
        for day in response.get("itinerary", []):
            if not isinstance(day, dict):
                continue
            matches = [concept for activity in day.get("activities", []) if isinstance(activity, dict)
                       for concept in matches_by_name.get(str(activity.get("name", "")).casefold(), ())]
            schedule = day.get("schedule", {})
            day["strategy_explanation"] = strategy.day_explanation(matches, schedule.get("free_time_minutes") if isinstance(schedule, dict) else None)

    @staticmethod
    def _primary_activity_ranking(ranked_activities: list) -> list:
        """Prefer verified experiences over places intended purely for meals.

        Discovery remains broad and food records are retained in their own
        Geoapify-backed planner.  A fallback preserves the prior behaviour for
        destinations where no other factual activity is available.
        """
        non_food = [item for item in ranked_activities if not TravelRecommender._is_meal_only_place(item.place)]
        return non_food or ranked_activities

    @staticmethod
    def _is_meal_only_place(place: dict) -> bool:
        categories = " ".join(str(value).casefold() for value in place.get("categories", []))
        meal_categories = (
            "catering.restaurant",
            "catering.cafe",
            "catering.food_court",
            "commercial.marketplace",
        )
        return any(category in categories for category in meal_categories)

    @staticmethod
    def _select_accommodation(candidates: list[dict], preferences: dict, destination: dict) -> dict | None:
        if not candidates:
            return None
        # ``candidates`` has already passed generic intent, mobility, budget,
        # and spatial-diversity ordering.  Selecting its leading candidate is
        # therefore more faithful than rotating away from a high-ranked match.
        # This deliberately has no experience-specific exception.
        del preferences, destination
        return candidates[0]

    @staticmethod
    def _ensure_strong_verified_experience(response: dict, ranked_activities: list, intents: list[IntentPreference]) -> None:
        """Reserve factual matches for any omitted high-priority user intent.

        This is intentionally concept-agnostic: the IntentAnalyzer remains free
        to emit new concepts, and only candidates whose *verified* Geoapify
        metadata matched them can be promoted.
        """
        required = {
            intent.concept for intent in intents
            if intent.polarity == "positive" and intent.strength in {"high", "very_high"}
        }
        if not required or not ranked_activities:
            return
        itinerary = response.get("itinerary", [])
        selected_names = {activity.get("name", "").casefold() for day in itinerary if isinstance(day, dict) for activity in day.get("activities", []) if isinstance(activity, dict)}
        selected_concepts = {
            concept for item in ranked_activities
            if item.place.get("name", "").casefold() in selected_names
            for concept in item.matched_concepts
        }
        unmet = required - selected_concepts
        if not unmet:
            return
        replacement = next(
            (item.place for item in ranked_activities
             if unmet.intersection(item.matched_concepts)
             and item.place.get("name", "").casefold() not in selected_names),
            None,
        )
        if replacement is None:
            return
        for day in itinerary:
            activities = day.get("activities") if isinstance(day, dict) else None
            if isinstance(activities, list) and activities:
                replace_index = next(
                    (index for index in range(len(activities) - 1, -1, -1)
                     if isinstance(activities[index], dict)
                     and not unmet.intersection(next(
                         (item.matched_concepts for item in ranked_activities
                          if item.place.get("name", "").casefold() == activities[index].get("name", "").casefold()),
                         (),
                     ))),
                    len(activities) - 1,
                )
                activities[replace_index] = {
                    "name": replacement["name"],
                    "address": str(replacement.get("address", "")),
                    "reason": "",
                }
                return

    @staticmethod
    def _remove_strong_negative_conflicts(response: dict, ranked_activities: list) -> None:
        """Replace an LLM-chosen strong negative match when a verified alternative exists.

        Ranking already demotes these records, but this final guard prevents a
        constrained LLM response from silently reintroducing a category the
        traveler strongly rejected.  It is entirely metadata-driven and does
        not assume a closed list of dislikes.
        """
        by_name = {
            str(item.place.get("name", "")).casefold(): item
            for item in ranked_activities
            if isinstance(item.place.get("name"), str)
        }
        selected_names = {
            str(activity.get("name", "")).casefold()
            for day in response.get("itinerary", []) if isinstance(day, dict)
            for activity in day.get("activities", []) if isinstance(activity, dict)
        }
        alternatives = [item for item in ranked_activities if not item.has_strong_negative_conflict]
        if not alternatives:
            return
        for day in response.get("itinerary", []):
            if not isinstance(day, dict):
                continue
            for activity in day.get("activities", []):
                if not isinstance(activity, dict):
                    continue
                selected = by_name.get(str(activity.get("name", "")).casefold())
                if selected is None or not selected.has_strong_negative_conflict:
                    continue
                replacement = next(
                    (item.place for item in alternatives
                     if str(item.place.get("name", "")).casefold() not in selected_names),
                    None,
                )
                if replacement is None:
                    continue
                selected_names.discard(str(activity.get("name", "")).casefold())
                selected_names.add(str(replacement["name"]).casefold())
                activity.update({"name": replacement["name"], "address": str(replacement.get("address", "")), "reason": ""})

    @staticmethod
    def _improve_spatial_diversity(response: dict, ranked_activities: list, intents: list[IntentPreference], mobility: MobilityProfile | None = None, accommodation: dict | None = None, routing: RoutingService | None = None, constraints: TripConstraints | None = None) -> None:
        """Use a verified alternate area when an LLM collapses the trip into one cluster.

        This is intentionally conservative: it changes at most one weaker
        activity and only if an unused, non-conflicting candidate is available
        in another data-derived spatial cluster.  The later strong-preference
        guard retains priority over geographic variety.
        """
        places = [item.place for item in ranked_activities]
        if len(places) < 3:
            return
        by_name = {str(item.place.get("name", "")).casefold(): item for item in ranked_activities}
        activities = [
            activity for day in response.get("itinerary", []) if isinstance(day, dict)
            for activity in day.get("activities", []) if isinstance(activity, dict)
        ]
        selected = [(activity, by_name.get(str(activity.get("name", "")).casefold())) for activity in activities]
        selected = [(activity, item) for activity, item in selected if item is not None]
        if len(selected) < 2:
            return
        clusters = {spatial_cluster(item.place, places) for _, item in selected}
        clusters.discard(None)
        if len(clusters) > 1:
            return
        selected_names = {str(activity.get("name", "")).casefold() for activity, _ in selected}
        def reachable_alternate(place: dict) -> bool:
            if not isinstance(accommodation, dict):
                return True
            distance = TravelRecommender._direct_distance_km(accommodation, place)
            if mobility and mobility.walking_only:
                return distance <= 5
            mode = mobility.planning_mode() if mobility else None
            if mode == "public_transport":
                # ORS has no transit profile; keep unverified transit choices
                # local rather than manufacturing a regional transit route.
                return distance <= 6
            if mode == "bicycle" and distance > 14:
                return False
            if mode in {"car", "motorcycle"} and distance > 35:
                return False
            if distance <= (4 if mode == "bicycle" else 8):
                return True
            if routing is None or mode not in {"car", "motorcycle", "bicycle"}:
                return False
            route_mode = "car" if mode == "motorcycle" else mode
            outward = routing.route(accommodation, place, route_mode)
            returning = routing.route(place, accommodation, route_mode)
            if any(item.data_status != "verified" or item.duration_minutes is None for item in (outward, returning)):
                return False
            return outward.duration_minutes + returning.duration_minutes <= min((constraints.max_daily_travel_minutes if constraints else None) or 180, 210)
        alternate = next(
            (item for item in ranked_activities
             if not item.has_strong_negative_conflict
             and str(item.place.get("name", "")).casefold() not in selected_names
             and reachable_alternate(item.place)
             and spatial_cluster(item.place, places) is not None
             and spatial_cluster(item.place, places) not in clusters),
            None,
        )
        if alternate is None:
            return
        # Do not displace a verified high-priority match if a weaker activity
        # is present.  A later coverage pass protects all required concepts.
        positive_concepts = {
            intent.concept for intent in intents
            if intent.polarity == "positive" and intent.strength in {"high", "very_high"}
        }
        replace_activity, _ = min(
            selected,
            key=lambda pair: (
                bool(positive_concepts.intersection(pair[1].matched_concepts)),
                pair[1].final_score,
            ),
        )
        replace_activity.update({"name": alternate.place["name"], "address": str(alternate.place.get("address", "")), "reason": ""})

    @staticmethod
    def _direct_distance_km(first: dict, second: dict) -> float:
        try:
            return DailyPlanner._distance_km(
                float(first["latitude"]), float(first["longitude"]),
                float(second["latitude"]), float(second["longitude"]),
            )
        except (KeyError, TypeError, ValueError):
            return 0.0

    def _ensure_regional_day(
        self, response: dict, ranked_activities: list, intents: list[IntentPreference],
        mobility: MobilityProfile, accommodation: dict | None, constraints: TripConstraints,
        excluded_names: set[str] | None = None,
    ) -> None:
        """Promote a coherent regional pair only when provider routes support it."""
        promote_regional_day(
            response.get("itinerary", []), ranked_activities, accommodation,
            mobility, constraints, TripStrategy.from_intents(intents), self.routing_service,
            excluded_names=excluded_names,
        )

    def _analyze_mobility(self, preferences: dict) -> MobilityProfile:
        analyzer = getattr(self.mobility_analyzer, "analyze", None)
        return analyzer(preferences) if callable(analyzer) else MobilityProfile.unknown()

    @staticmethod
    def _llm_place_data(place: dict) -> dict:
        """Expose only factual, decision-relevant data; never raw provider payloads."""
        return {
            key: place[key]
            for key in ("name", "address", "categories", "city", "country")
            if key in place
        }

    @staticmethod
    def _selected_place_ranking(response: dict, ranked_accommodations: list, ranked_activities: list, ranked_food: list | None = None) -> dict:
        """Return deterministic score evidence for selected places without changing UI."""
        def details(name: object, candidates: list) -> dict | None:
            if not isinstance(name, str):
                return None
            candidate = next(
                (item for item in candidates if item.place.get("name", "").casefold() == name.casefold()),
                None,
            )
            if candidate is None:
                return None
            return {
                "name": candidate.place.get("name", ""),
                "preference_score": candidate.preference_score,
                "relevance_score": candidate.relevance_score,
                "quality_score": candidate.quality_score,
                "popularity_score": candidate.popularity_score,
                "data_confidence_score": candidate.data_confidence_score,
                "final_score": candidate.final_score,
                "matched_concepts": list(candidate.matched_concepts),
                "quality_evidence": candidate.quality_explanation,
                "mobility_score": candidate.mobility_score,
            }

        accommodation = response.get("selected_accommodation", {})
        activity_details = []
        for day in response.get("itinerary", []):
            if isinstance(day, dict):
                for activity in day.get("activities", []):
                    if isinstance(activity, dict):
                        detail = details(activity.get("name"), ranked_activities)
                        if detail is not None:
                            activity_details.append({"name": activity["name"], **detail})
        food_details = []
        for day in response.get("itinerary", []):
            if not isinstance(day, dict):
                continue
            for meal in day.get("meals", []):
                if not isinstance(meal, dict):
                    continue
                for option in meal.get("options", [])[:1]:
                    if isinstance(option, dict):
                        detail = details(option.get("name"), ranked_food or [])
                        if detail is not None:
                            food_details.append({"name": option["name"], **detail})
        return {
            "accommodation": details(accommodation.get("name") if isinstance(accommodation, dict) else None, ranked_accommodations),
            "activities": activity_details,
            "food": food_details,
        }

    @staticmethod
    def _replace_reasons_with_verified_matches(
        response: dict,
        ranked_accommodations: list,
        ranked_activities: list,
    ) -> None:
        """Avoid presenting an LLM's unsupported facility or quality claims as facts."""
        ranks_by_name = {
            item.place["name"].casefold(): item
            for item in [*ranked_accommodations, *ranked_activities]
            if isinstance(item.place.get("name"), str)
        }

        def safe_reason(name: str) -> str:
            matched = ranks_by_name.get(name.casefold())
            if matched and matched.matched_concepts:
                concepts = ", ".join(concept.replace("_", " ") for concept in matched.matched_concepts)
                reason = f"Prioritized because verified Geoapify categories match: {concepts}."
                if matched.quality_score or matched.popularity_score:
                    return f"{reason} {matched.quality_explanation}"
                return reason
            if matched and (matched.quality_score or matched.popularity_score):
                return f"Included from the verified Geoapify places. {matched.quality_explanation}"
            return "Included from the verified Geoapify places to create a balanced itinerary."

        accommodation = response.get("selected_accommodation", {})
        if isinstance(accommodation, dict) and isinstance(accommodation.get("name"), str):
            accommodation["reason"] = safe_reason(accommodation["name"])
        for day in response.get("itinerary", []):
            if isinstance(day, dict):
                for activity in day.get("activities", []):
                    if isinstance(activity, dict) and isinstance(activity.get("name"), str):
                        activity["reason"] = safe_reason(activity["name"])

    @staticmethod
    def _legacy_validate_recommendation(
        response: dict,
        travel_data: dict,
        duration_days: int,
    ) -> None:

        if not isinstance(response, dict):
            raise ValueError(
                "Travel recommender returned invalid data."
            )

        # ============================================
        # CHECK ACCOMMODATION
        # ============================================

        accommodation = response.get(
            "selected_accommodation"
        )

        if not isinstance(accommodation, dict):
            raise ValueError(
                "No valid accommodation was selected."
            )

        real_accommodations = {
            item["name"]: item
            for item in travel_data.get(
                "accommodations",
                []
            )
            if item.get("name")
        }

        selected_name = accommodation.get(
            "name",
            ""
        )

        matching_accommodation = next(
            (
                name
                for name in real_accommodations
                if name.lower() == selected_name.lower()
            ),
            None,
        )

        if matching_accommodation is None:
            raise ValueError(
                "AI selected an accommodation that was not "
                "provided by the travel data."
            )

        # Always use the exact real name and address.
        accommodation["name"] = (
            matching_accommodation
        )

        accommodation["address"] = (
            real_accommodations[
                matching_accommodation
            ].get(
                "address",
                accommodation.get("address", "")
            )
        )

        # ============================================
        # CHECK ITINERARY
        # ============================================

        itinerary = response.get(
            "itinerary"
        )

        if not isinstance(itinerary, list):
            raise ValueError(
                "Invalid itinerary returned by AI."
            )

        if len(itinerary) != duration_days:
            raise ValueError(
                "AI did not create an itinerary for every day."
            )

        expected_days = list(
            range(1, duration_days + 1)
        )

        actual_days = [
            day.get("day")
            for day in itinerary
            if isinstance(day, dict)
        ]

        if actual_days != expected_days:
            raise ValueError(
                "Itinerary days are missing or in the wrong order."
            )

        # ============================================
        # REAL ACTIVITIES
        # ============================================

        real_activities = {
            item["name"]: item
            for item in travel_data.get(
                "activities",
                []
            )
            if item.get("name")
        }

        # Keywords used to identify monuments/memorials.
        monument_keywords = (
            "monument",
            "memorial",
            "ausammas",
            "mälestusmärk",
        )

        # Keep track of every activity already used.
        used_activities = set()

        # ============================================
        # CHECK EVERY DAY
        # ============================================

        for day in itinerary:

            activities = day.get(
                "activities",
                []
            )

            # ----------------------------------------
            # A day needs at least one real activity. Its practical capacity is
            # calculated by DailyPlanner, not by a fixed activity count.
            # ----------------------------------------

            if not isinstance(activities, list) or not activities:
                raise ValueError(
                    "Each day must contain at least one activity."
                )

            # Number of monuments in this day.
            monument_count = 0

            # ----------------------------------------
            # CHECK EVERY ACTIVITY
            # ----------------------------------------

            for activity in activities:

                activity_name = activity.get(
                    "name",
                    ""
                )

                # ------------------------------------
                # Activity must exist in Geoapify data
                # ------------------------------------

                matching_activity = next(
                    (
                        name
                        for name in real_activities
                        if name.lower() == activity_name.lower()
                    ),
                    None,
                )

                if matching_activity is None:
                    raise ValueError(
                        "AI selected an activity that was not "
                        "provided by the travel data."
                    )

                # ------------------------------------
                # NO DUPLICATE ACTIVITIES
                # ------------------------------------

                normalized_activity_name = (
                    matching_activity
                    .lower()
                    .strip()
                )

                if (
                    normalized_activity_name
                    in used_activities
                ):
                    raise ValueError(
                        f"Activity '{matching_activity}' "
                        "is repeated in the itinerary."
                    )

                used_activities.add(
                    normalized_activity_name
                )

                # ------------------------------------
                # Use real Geoapify data
                # ------------------------------------

                activity["name"] = (
                    matching_activity
                )

                activity["address"] = (
                    real_activities[
                        matching_activity
                    ].get(
                        "address",
                        activity.get(
                            "address",
                            ""
                        )
                    )
                )

                # ------------------------------------
                # MONUMENT COUNT
                # ------------------------------------

                normalized_name = (
                    matching_activity.lower()
                )

                if any(
                    keyword in normalized_name
                    for keyword in monument_keywords
                ):
                    monument_count += 1

            # ----------------------------------------
            # Maximum one monument per day
            # ----------------------------------------

            if monument_count > 1:
                raise ValueError(
                    f"Day {day['day']} contains more than "
                    "one monument or memorial."
                )
