import os
import requests
from dotenv import load_dotenv


load_dotenv()

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")


def get_coordinates(city: str, country: str):
    if not GEOAPIFY_API_KEY:
        raise ValueError("GEOAPIFY_API_KEY is not configured.")

    url = "https://api.geoapify.com/v1/geocode/search"

    params = {
        "text": f"{city}, {country}",
        "limit": 1,
        "apiKey": GEOAPIFY_API_KEY,
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    features = data.get("features", [])

    if not features:
        raise ValueError(f"Could not find coordinates for {city}, {country}")

    properties = features[0].get("properties", {})

    # A destination search must resolve to a geographic destination, not a
    # similarly named street.  Without this guard, e.g. "Val Gardena,
    # Dolomites" can resolve to "Via Val Gardena" in an unrelated town and
    # the subsequent place search looks factual while being hundreds of
    # kilometres from the requested trip.  It is safer to report an
    # unavailable real-plan lookup than to present that as the destination.
    if properties.get("result_type") in {"street", "amenity", "building"}:
        raise ValueError(
            f"Could not find a geographic destination match for {city}, {country}."
        )

    return {
        "city": city,
        "country": country,
        "latitude": properties.get("lat"),
        "longitude": properties.get("lon"),
    }
