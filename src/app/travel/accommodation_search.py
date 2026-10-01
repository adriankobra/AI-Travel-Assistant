import os
import requests
from dotenv import load_dotenv

from app.travel.geocoding import get_coordinates
from app.travel.category_config import ACCOMMODATION_CATEGORIES
from app.travel.place import Place, deduplicate_places


load_dotenv()

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")


def search_accommodations(
    latitude: float,
    longitude: float,
    accommodation_type: str,
    radius: int = 5000,
    limit: int = 5,
):
    if not GEOAPIFY_API_KEY:
        raise ValueError("GEOAPIFY_API_KEY is not configured.")

    category = ACCOMMODATION_CATEGORIES.get(accommodation_type)

    if not category:
        raise ValueError(
            f"Unsupported accommodation type: {accommodation_type}"
        )

    url = "https://api.geoapify.com/v2/places"

    params = {
        "categories": category,
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

        place = Place.from_geoapify(properties, place_type=accommodation_type)
        if place is None:
            continue

        places.append(place)

    return [place.to_dict() for place in deduplicate_places(places)]


def find_accommodations_for_city(
    city: str,
    country: str,
    accommodation_type: str,
    radius: int = 5000,
    limit: int = 5,
):
    location = get_coordinates(city, country)

    return search_accommodations(
        latitude=location["latitude"],
        longitude=location["longitude"],
        accommodation_type=accommodation_type,
        radius=radius,
        limit=limit,
    )
