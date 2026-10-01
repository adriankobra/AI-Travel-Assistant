import os
import requests
from dotenv import load_dotenv

from app.travel.geocoding import get_coordinates
from app.travel.category_config import ACTIVITY_CATEGORIES, FOOD_CATEGORIES
from app.travel.place import Place, deduplicate_places


load_dotenv()

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")


def _search_places(
    latitude: float,
    longitude: float,
    categories: tuple[str, ...],
    radius: int = 5000,
    limit: int = 40,
) -> list[dict]:
    if not GEOAPIFY_API_KEY:
        raise ValueError("GEOAPIFY_API_KEY is not configured.")

    url = "https://api.geoapify.com/v2/places"

    params = {
        "categories": ",".join(categories),
        "filter": f"circle:{longitude},{latitude},{radius}",
        "bias": f"proximity:{longitude},{latitude}",
        "limit": limit,
        "apiKey": GEOAPIFY_API_KEY,
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    places: list[Place] = []

    for feature in data.get("features", []):
        properties = feature.get("properties", {})

        place = Place.from_geoapify(properties)
        if place is None:
            continue

        places.append(place)

    return [place.to_dict() for place in deduplicate_places(places)]


def search_activities(
    latitude: float,
    longitude: float,
    radius: int = 5000,
    limit: int = 40,
) -> list[dict]:
    return _search_places(latitude, longitude, ACTIVITY_CATEGORIES, radius, limit)


def search_food_places(
    latitude: float,
    longitude: float,
    radius: int = 5000,
    limit: int = 15,
) -> list[dict]:
    """Return only real Geoapify food-category places for meal choices."""
    return _search_places(latitude, longitude, FOOD_CATEGORIES, radius, limit)


def find_activities_for_city(
    city: str,
    country: str,
    radius: int = 5000,
    limit: int = 40,
):
    location = get_coordinates(city, country)

    return search_activities(
        latitude=location["latitude"],
        longitude=location["longitude"],
        radius=radius,
        limit=limit,
    )


def find_food_places_for_city(
    city: str,
    country: str,
    radius: int = 5000,
    limit: int = 15,
) -> list[dict]:
    location = get_coordinates(city, country)
    return search_food_places(location["latitude"], location["longitude"], radius, limit)
