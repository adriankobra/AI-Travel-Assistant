"""Verified Geoapify category configuration used for travel-place discovery.

Keys below are taken from Geoapify's Places API category reference.  Keep this
as the one place to extend the discovery vocabulary; intent analysis remains
open-ended and simply reports requests which no configured, returned category
can verify.
"""

from __future__ import annotations


ACCOMMODATION_CATEGORIES = {
    "Hotel": "accommodation.hotel",
    "Apartment": "accommodation.apartment",
    "Hostel": "accommodation.hostel",
    "Guesthouse": "accommodation.guest_house",
    "Camping": "camping.camp_site",
}

# A category can occur in more than one user-facing group only when that is
# factually true. Geoapify returns the actual category list with each place.
ACTIVITY_CATEGORY_GROUPS: dict[str, tuple[str, ...]] = {
    "attractions_and_culture": (
        "tourism.attraction", "tourism.sights", "entertainment.museum",
        "entertainment.culture", "heritage.unesco",
    ),
    "wellness_and_water": (
        "leisure.spa", "leisure.spa.public_bath", "leisure.spa.sauna",
        "service.beauty.spa", "beach", "beach.beach_resort",
        "sport.swimming_pool", "entertainment.water_park", "natural.coastal",
        "natural.water",
    ),
    "rentals": ("rental.bicycle", "rental.car", "rental.boat"),
    "nature_and_outdoors": (
        "leisure.park", "leisure.park.garden", "leisure.park.nature_reserve",
        "natural.forest", "natural.protected_area", "natural.mountain",
        "national_park", "highway.path", "sport.fitness", "sport.golf_course",
    ),
    "food_and_cafes": (
        "catering.restaurant", "catering.cafe", "catering.food_court",
        "commercial.marketplace",
    ),
    "nightlife": ("catering.bar", "catering.pub", "catering.biergarten"),
    "family": (
        "leisure.playground", "entertainment.activity_park", "entertainment.aquarium",
        "entertainment.theme_park", "entertainment.zoo", "entertainment.bowling_alley",
    ),
    "shopping": (
        "commercial.shopping_mall", "commercial.marketplace", "commercial.hobby",
        "commercial.outdoor_and_sport",
    ),
}


def _unique_categories() -> tuple[str, ...]:
    return tuple(dict.fromkeys(category for group in ACTIVITY_CATEGORY_GROUPS.values() for category in group))


ACTIVITY_CATEGORIES = _unique_categories()

# Meal discovery uses only categories verified by Geoapify.  Cuisine is not
# inferred from a name and remains unavailable unless a provider returns it.
FOOD_CATEGORIES = ACTIVITY_CATEGORY_GROUPS["food_and_cafes"]


# Semantic terms describe verified category metadata, never unverified business
# features. They are aliases for common *concepts*, not a list of allowed user
# preferences: an unknown concept remains intact and is reported as unmatched.
CONCEPT_CATEGORY_TERMS = {
    "relaxation": {"spa", "beach", "coastal", "park", "nature", "water", "sauna", "public_bath"},
    "spa": {"spa", "sauna", "public_bath", "wellness"},
    "wellness": {"spa", "sauna", "public_bath", "wellness"},
    "walking": {"pedestrian", "footway", "promenade", "path", "park", "trail"},
    "swimming": {"swimming_pool", "water_park", "beach", "water", "coastal"},
    "water_activities": {"swimming_pool", "water_park", "beach", "water", "coastal", "boat"},
    "beach": {"beach", "coastal", "water"},
    "near_the_sea": {"beach", "coastal", "sea", "water"},
    "bike_rental": {"bicycle"},
    "bicycle_rental": {"bicycle"},
    "car_rental": {"car"},
    "nature": {"park", "nature", "forest", "beach", "path", "mountain", "protected_area"},
    "hiking": {"path", "forest", "nature", "mountain", "protected_area", "national_park"},
    "local_food": {"restaurant", "cafe", "marketplace", "food_court", "catering"},
    "food": {"restaurant", "cafe", "marketplace", "food_court", "catering"},
    "cafe": {"cafe"},
    "nightlife": {"bar", "pub", "biergarten"},
    "family_activity": {"zoo", "playground", "aquarium", "theme_park", "activity_park", "bowling_alley"},
    "family": {"zoo", "playground", "aquarium", "theme_park", "activity_park", "bowling_alley"},
    "children": {"zoo", "playground", "aquarium", "theme_park", "activity_park", "bowling_alley"},
    "shopping": {"shopping_mall", "marketplace", "hobby", "outdoor_and_sport"},
    "romantic": {"beach", "coastal", "park", "garden", "water"},
    "adventure": {"activity_park", "outdoor_and_sport", "path", "forest", "mountain", "water_park"},
    "history": {"heritage", "museum", "sights", "attraction", "culture"},
    "architecture": {"heritage", "sights", "attraction", "culture"},
    "famous_places": {"attraction", "sights", "heritage", "museum"},
    "quiet": {"park", "garden", "nature", "forest", "beach", "coastal"},
    "outdoors": {"park", "garden", "nature", "forest", "path", "beach", "coastal"},
    "active": {"activity_park", "outdoor_and_sport", "path", "forest", "mountain"},
}


CATEGORY_IMPORTANCE_WEIGHTS = {
    "tourism.attraction": 4,
    "tourism.sights": 3,
    "entertainment.museum": 3,
    "entertainment.culture": 3,
    "leisure.spa": 3,
    "beach": 3,
    "leisure.park": 2,
    "catering.restaurant": 2,
    "entertainment": 2,
}
