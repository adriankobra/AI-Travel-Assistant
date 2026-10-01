import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from app.travel.travel_data import get_travel_data

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


data = get_travel_data(
    city="Pärnu",
    country="Estonia",
    accommodation_type="Apartment",
)


print("\n=== DESTINATION ===")
print(data["destination"])

print("\n=== ACCOMMODATIONS ===")

for accommodation in data["accommodations"]:
    print(accommodation)

print("\n=== ACTIVITIES ===")

for activity in data["activities"]:
    print(activity)
