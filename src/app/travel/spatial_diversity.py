"""Small, data-driven geographic variety helpers for verified places."""

from __future__ import annotations

from math import atan2, cos, radians, sin, sqrt
from typing import Any, Iterable


def spatial_cluster(place: dict[str, Any], places: Iterable[dict[str, Any]]) -> str | None:
    """Return an adaptive area bucket derived from the candidate distribution.

    The bucket has no city-specific radius: its scale is the median distance of
    all coordinate-backed candidates from their geographic centre.  It is only
    used to avoid repeatedly favouring one small area when alternatives exist.
    """
    coordinates = [_coordinates(item) for item in places]
    coordinates = [item for item in coordinates if item is not None]
    point = _coordinates(place)
    if point is None or len(coordinates) < 3:
        return None
    center = (sum(item[0] for item in coordinates) / len(coordinates), sum(item[1] for item in coordinates) / len(coordinates))
    distances = sorted(_distance_meters(point, center) for point in coordinates)
    scale = distances[len(distances) // 2]
    if scale <= 1:
        return "central"
    distance = _distance_meters(point, center)
    bearing = int((atan2(point[1] - center[1], point[0] - center[0]) + 3.1415926535) / (3.1415926535 / 2)) % 4
    ring = 0 if distance <= scale else 1 if distance <= scale * 2 else 2
    return f"{ring}:{bearing}"


def diversify(places: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Interleave ranked verified places by adaptive geographic cluster.

    Ranking order remains primary: this only moves the next available distinct
    cluster ahead of a repeat, and falls back unchanged when data is concentrated.
    """
    remaining = list(places)
    ordered: list[dict[str, Any]] = []
    used_clusters: set[str] = set()
    while remaining:
        index = next((i for i, item in enumerate(remaining) if (cluster := spatial_cluster(item, remaining + ordered)) is None or cluster not in used_clusters), 0)
        item = remaining.pop(index)
        ordered.append(item)
        cluster = spatial_cluster(item, remaining + ordered)
        if cluster is not None:
            used_clusters.add(cluster)
    return ordered


def _coordinates(place: dict[str, Any]) -> tuple[float, float] | None:
    try:
        return float(place["latitude"]), float(place["longitude"])
    except (KeyError, TypeError, ValueError):
        return None


def _distance_meters(first: tuple[float, float], second: tuple[float, float]) -> float:
    radius = 6_371_000
    d_lat, d_lon = radians(second[0] - first[0]), radians(second[1] - first[1])
    value = sin(d_lat / 2) ** 2 + cos(radians(first[0])) * cos(radians(second[0])) * sin(d_lon / 2) ** 2
    return radius * 2 * atan2(sqrt(value), sqrt(1 - value))
