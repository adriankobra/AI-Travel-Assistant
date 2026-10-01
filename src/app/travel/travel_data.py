from app.travel.accommodation_search import find_accommodations_for_city
from app.travel.activity_search import find_activities_for_city, find_food_places_for_city


def get_travel_data(
    city: str,
    country: str,
    accommodation_type: str,
    accommodation_limit: int = 20,
    activity_limit: int = 60,
    activity_radius: int = 5000,
):
    accommodations = find_accommodations_for_city(
        city=city,
        country=country,
        accommodation_type=accommodation_type,
        limit=accommodation_limit,
    )

    activities = find_activities_for_city(
        city=city,
        country=country,
        limit=activity_limit, radius=activity_radius,
    )
    food_options = find_food_places_for_city(
        city=city,
        country=country,
        limit=72 if activity_radius >= 12_000 else 36, radius=activity_radius,
    )

    return {
        "destination": {
            "city": city,
            "country": country,
        },
        "accommodations": accommodations,
        "activities": activities,
        "food_options": food_options,
    }
