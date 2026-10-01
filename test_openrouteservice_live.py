"""Optional live ORS smoke test. Run directly; it is not part of offline tests."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from app.travel.routing_openrouteservice import OpenRouteServiceRoutingService


def main() -> int:
    # The provider reads ORS_API_KEY from the project .env file.  If it is not
    # configured, each route is simply returned as unavailable below.
    service = OpenRouteServiceRoutingService()

    origin = {"latitude": 56.9496, "longitude": 24.1052}
    destination = {"latitude": 56.9539, "longitude": 24.1130}
    results = [service.route(origin, destination, mode) for mode in ("walking", "driving", "bicycle")]
    if not all(route.status == "success" and route.data_status == "verified" for route in results):
        print("ORS live test skipped or unavailable: configure ORS_API_KEY and check provider connectivity.")
        return 0
    for route in results:
        print(f"{route.transport_mode}: {route.distance_meters:.0f} m, {route.duration_minutes} min, {route.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
