"""Deterministic validation for AI-selected, Geoapify-backed travel plans."""

from __future__ import annotations

from typing import Any
from app.travel.mobility import MobilityProfile, WALKING_DISTANCE_LIMIT_METERS


class TravelPlanValidationError(ValueError):
    """Raised when an AI recommendation violates a real-data travel-plan rule."""


class TravelPlanValidator:
    """Validate an itinerary and restore verified names and addresses from real data."""

    monument_keywords = ("monument", "memorial", "ausammas", "mälestusmärk")

    def validate(self, response: dict[str, Any], travel_data: dict[str, Any], duration_days: int, mobility_profile: MobilityProfile | None = None) -> None:
        if not isinstance(response, dict):
            raise TravelPlanValidationError("Travel recommender returned invalid data.")
        accommodation = response.get("selected_accommodation")
        if not isinstance(accommodation, dict):
            raise TravelPlanValidationError("No valid accommodation was selected.")
        self._verify_accommodation(accommodation, self._places_by_name(travel_data.get("accommodations", [])))
        itinerary = response.get("itinerary")
        if not isinstance(itinerary, list):
            raise TravelPlanValidationError("Invalid itinerary returned by AI.")
        if len(itinerary) != duration_days:
            raise TravelPlanValidationError("AI did not create an itinerary for every day.")
        if [day.get("day") for day in itinerary if isinstance(day, dict)] != list(range(1, duration_days + 1)):
            raise TravelPlanValidationError("Itinerary days are missing or in the wrong order.")
        self._verify_activities(itinerary, self._places_by_name(travel_data.get("activities", [])), mobility_profile)
        self._verify_food_options(itinerary, self._places_by_name(travel_data.get("food_options", [])))
        self._verify_timeline(itinerary)

    @staticmethod
    def _places_by_name(places: object) -> dict[str, dict[str, Any]]:
        if not isinstance(places, list):
            return {}
        return {place["name"].casefold(): place for place in places if isinstance(place, dict) and isinstance(place.get("name"), str) and place["name"].strip()}

    @staticmethod
    def _verify_accommodation(accommodation: dict[str, Any], real_places: dict[str, dict[str, Any]]) -> None:
        name = accommodation.get("name")
        key = name.casefold() if isinstance(name, str) else ""
        if key not in real_places:
            raise TravelPlanValidationError("AI selected an accommodation that was not provided by the travel data.")
        real = real_places[key]
        accommodation["name"] = real["name"]
        accommodation["address"] = real.get("address", accommodation.get("address", ""))
        TravelPlanValidator._restore_place_fields(accommodation, real)

    def _verify_activities(self, itinerary: list[Any], real_places: dict[str, dict[str, Any]], mobility_profile: MobilityProfile | None = None) -> None:
        used: set[str] = set()
        for day in itinerary:
            if not isinstance(day, dict):
                raise TravelPlanValidationError("Invalid itinerary day returned by AI.")
            activities = day.get("activities", [])
            if not isinstance(activities, list) or not activities:
                raise TravelPlanValidationError("Each day must contain at least one activity.")
            monuments = 0
            previous_end: int | None = None
            for activity in activities:
                if not isinstance(activity, dict):
                    raise TravelPlanValidationError("Invalid activity returned by AI.")
                name = activity.get("name")
                key = name.casefold().strip() if isinstance(name, str) else ""
                if key not in real_places:
                    raise TravelPlanValidationError("AI selected an activity that was not provided by the travel data.")
                if key in used:
                    raise TravelPlanValidationError(f"Activity '{real_places[key]['name']}' is repeated in the itinerary.")
                used.add(key)
                real = real_places[key]
                self._verify_mobility(real, mobility_profile)
                activity["name"] = real["name"]
                activity["address"] = real.get("address", activity.get("address", ""))
                self._restore_place_fields(activity, real)
                start, end = self._verify_schedule_entry(activity)
                if start is not None and previous_end is not None and start < previous_end:
                    raise TravelPlanValidationError("Activity schedules overlap within a day.")
                if end is not None:
                    previous_end = end
                monuments += int(any(keyword in key for keyword in self.monument_keywords))
            if monuments > 1:
                raise TravelPlanValidationError(f"Day {day['day']} contains more than one monument or memorial.")

    @staticmethod
    def _restore_place_fields(target: dict[str, Any], real: dict[str, Any]) -> None:
        for field in ("latitude", "longitude", "place_id", "categories", "datasource", "type"):
            if field in real:
                target[field] = real[field]

    def _verify_food_options(self, itinerary: list[Any], real_food: dict[str, dict[str, Any]]) -> None:
        """Validate options only when food discovery was supplied for this plan."""
        if not real_food:
            return
        for day in itinerary:
            if not isinstance(day, dict):
                continue
            for meal in day.get("meals", []):
                if not isinstance(meal, dict):
                    raise TravelPlanValidationError("Invalid meal entry in itinerary.")
                for option in meal.get("options", []):
                    if not isinstance(option, dict) or not isinstance(option.get("name"), str):
                        raise TravelPlanValidationError("Invalid food option in itinerary.")
                    real = real_food.get(option["name"].casefold())
                    if real is None:
                        raise TravelPlanValidationError("Food option was not returned by Geoapify.")
                    self._restore_place_fields(option, real)
                    option["address"] = real.get("address", option.get("address", ""))

    def _verify_timeline(self, itinerary: list[Any]) -> None:
        for day in itinerary:
            if not isinstance(day, dict):
                continue
            previous_end: int | None = None
            for item in day.get("items", []):
                if not isinstance(item, dict):
                    raise TravelPlanValidationError("Invalid timeline item.")
                start, end = item.get("start_time"), item.get("end_time")
                if start is not None and end is not None:
                    try:
                        start_minutes, end_minutes = self._time_to_minutes(start), self._time_to_minutes(end)
                    except (TypeError, ValueError) as error:
                        raise TravelPlanValidationError("Timeline item has an invalid time.") from error
                    if end_minutes < start_minutes:
                        raise TravelPlanValidationError("Timeline item has an invalid duration.")
                    if previous_end is not None and start_minutes < previous_end:
                        raise TravelPlanValidationError("Timeline items overlap within a day.")
                    previous_end = end_minutes
                if item.get("item_type") == "travel":
                    verified = item.get("travel_time_data_status") == "verified"
                    if verified and (not isinstance(item.get("travel_duration_minutes"), int) or item.get("travel_distance_meters") is None):
                        raise TravelPlanValidationError("Verified travel item is missing route distance or duration.")
                    if not verified and item.get("travel_distance_meters") is not None:
                        raise TravelPlanValidationError("Unavailable travel item cannot claim a verified distance.")

    @staticmethod
    def _verify_mobility(place: dict[str, Any], profile: MobilityProfile | None) -> None:
        if profile is None:
            return
        categories = " ".join(str(item).casefold() for item in place.get("categories", []))
        distance = place.get("distance_meters")
        if profile.walking_only and isinstance(distance, (int, float)) and distance > WALKING_DISTANCE_LIMIT_METERS:
            raise TravelPlanValidationError("Walking-only mobility profile cannot include a verified far-away place.")
        if profile.rental_car_allowed is False and "rental.car" in categories:
            raise TravelPlanValidationError("Mobility profile does not allow car rental.")

    @staticmethod
    def _verify_schedule_entry(activity: dict[str, Any]) -> tuple[int | None, int | None]:
        """Validate optional planner timing metadata without requiring it from old callers."""
        start, end = activity.get("start_time"), activity.get("end_time")
        if start is None and end is None:
            return None, None
        if not isinstance(start, str) or not isinstance(end, str):
            raise TravelPlanValidationError("Activity schedule is incomplete.")
        try:
            start_minutes = TravelPlanValidator._time_to_minutes(start)
            end_minutes = TravelPlanValidator._time_to_minutes(end)
        except ValueError as error:
            raise TravelPlanValidationError("Activity schedule has an invalid time.") from error
        if end_minutes <= start_minutes:
            raise TravelPlanValidationError("Activity schedule has an invalid duration.")
        return start_minutes, end_minutes

    @staticmethod
    def _time_to_minutes(value: str) -> int:
        hour, minute = value.split(":")
        result = int(hour) * 60 + int(minute)
        if not 0 <= result < 24 * 60:
            raise ValueError(value)
        return result
