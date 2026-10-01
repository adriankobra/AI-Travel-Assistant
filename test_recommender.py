import sys
from pathlib import Path

# Add src to Python path
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.travel.travel_data import get_travel_data
from app.ai.travel_recommender import TravelRecommender


# ============================================
# TEST DATA
# ============================================

city = "Pärnu"
country = "Estonia"

accommodation_type = "Hotel"

duration_days = 3


preferences = {
    "continent": "Europe",
    "countries": ["Estonia"],
    "trip_types": [
        "🏖️ Beach & Relaxation",
        "🍴 Food & Local Culture",
    ],
    "travel_style": "Budget",
    "budget": "Under €500",
    "duration": "2–3 days",
    "accommodation": "Hotel",
    "travellers": "Couple",
    "traveller_count": 2,
    "additional_preferences": "Near the sea",
}


# ============================================
# GET REAL DATA FROM GEOAPIFY
# ============================================

print("\nGetting real travel data from Geoapify...\n")

travel_data = get_travel_data(
    city=city,
    country=country,
    accommodation_type=accommodation_type,
    accommodation_limit=5,
    activity_limit=15,
)


# ============================================
# SHOW REAL ACCOMMODATIONS
# ============================================

print("REAL ACCOMMODATIONS:")

for accommodation in travel_data["accommodations"]:
    print(
        f"- {accommodation['name']}"
        f" | {accommodation.get('address', '')}"
    )


# ============================================
# SHOW REAL ACTIVITIES
# ============================================

print("\nREAL ACTIVITIES:")

for activity in travel_data["activities"]:
    print(
        f"- {activity['name']}"
        f" | {activity.get('address', '')}"
    )


# ============================================
# RUN AI RECOMMENDER
# ============================================

print("\nGenerating AI travel recommendation...\n")

recommender = TravelRecommender()

result = recommender.recommend(
    preferences=preferences,
    destination={
        "city": city,
        "country": country,
    },
    travel_data=travel_data,
    duration_days=duration_days,
)


# ============================================
# SHOW SELECTED ACCOMMODATION
# ============================================

print("\n" + "=" * 60)
print("SELECTED ACCOMMODATION")
print("=" * 60)

accommodation = result["selected_accommodation"]

print(f"Name: {accommodation['name']}")
print(f"Address: {accommodation['address']}")
print(f"Reason: {accommodation['reason']}")


# ============================================
# SHOW ITINERARY
# ============================================

print("\n" + "=" * 60)
print("ITINERARY")
print("=" * 60)

for day in result["itinerary"]:

    title = day["title"]

    if title.lower().startswith(f"day {day['day']}:"):
        title = title.split(":", 1)[1].strip()

    print(f"\nDAY {day['day']}: {title}")

    for activity in day["activities"]:
        print(f"  - {activity['name']}")
        print(f"    Address: {activity['address']}")
        print(f"    Reason: {activity['reason']}")


# ============================================
# VALIDATION
# ============================================

print("\n" + "=" * 60)
print("VALIDATION")
print("=" * 60)


# Check number of days

assert len(result["itinerary"]) == duration_days

print("✓ Correct number of days")


# Check day numbers

actual_days = [
    day["day"]
    for day in result["itinerary"]
]

expected_days = list(range(1, duration_days + 1))

assert actual_days == expected_days

print("✓ Correct day numbers")


# Check accommodation

real_accommodation_names = {
    item["name"].lower()
    for item in travel_data["accommodations"]
}

assert accommodation["name"].lower() in real_accommodation_names

print("✓ Accommodation exists in Geoapify data")


# ============================================
# CHECK ACTIVITIES
# ============================================

real_activity_names = {
    item["name"].lower()
    for item in travel_data["activities"]
}

used_activities = set()


for day in result["itinerary"]:

    activities = day["activities"]

    # Daily capacity is dynamic. At least one real activity must fit.

    assert len(activities) >= 1

    print(
        f"✓ Day {day['day']} has "
        f"{len(activities)} activities"
    )

    monument_count = 0

    for activity in activities:

        activity_name = activity["name"]

        # Activity must exist in Geoapify

        assert activity_name.lower() in real_activity_names

        # Activity must not be repeated

        normalized_name = activity_name.lower().strip()

        assert normalized_name not in used_activities, (
            f"Activity '{activity_name}' "
            "is repeated in the itinerary."
        )

        used_activities.add(normalized_name)

        assert activity["duration_data_status"] in {"verified", "estimated"}
        assert activity["travel_time_data_status"] == "unavailable"
        assert activity["start_time"] < activity["end_time"]

        # Check monuments / memorials

        monument_keywords = (
            "monument",
            "memorial",
            "ausammas",
            "mälestusmärk",
        )

        if any(
            keyword in normalized_name
            for keyword in monument_keywords
        ):
            monument_count += 1

    # Maximum one monument per day

    assert monument_count <= 1, (
        f"Day {day['day']} contains more than "
        "one monument or memorial."
    )


print("✓ All activities exist in Geoapify data")
print("✓ No activity is repeated")
print("✓ Maximum one monument/memorial per day")
print("✓ Dynamic schedules are labelled and non-empty")


# ============================================
# SUCCESS
# ============================================

print("\n" + "=" * 60)
print("TEST COMPLETED SUCCESSFULLY")
print("=" * 60)
