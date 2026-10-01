"""A small, key-free Leaflet map rendered with OpenStreetMap tiles."""

from __future__ import annotations

import html
import json
from typing import Any

import streamlit.components.v1 as components


def itinerary_map_data(accommodation: dict[str, Any] | None, itinerary: list[dict[str, Any]]) -> dict[str, Any]:
    """Map markers and per-day ordered stop connectors from the current plan."""
    points: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    if isinstance(accommodation, dict):
        points.append(_point(accommodation, "Accommodation", "#087ea4"))
    for day in itinerary:
        if not isinstance(day, dict):
            continue
        day_number = day.get("day", "")
        stop = 0
        for item in day.get("items", []):
            if isinstance(item, dict) and item.get("item_type") == "activity":
                stop += 1
                # Keep a display label for people and an explicit route flag for
                # code.  The old implementation inferred the latter from the
                # label text and silently omitted all activity points.
                points.append(_point(item, f"Day {day_number} · Stop {stop}", "#0ea5c6"))
        for meal in day.get("meals", []):
            if isinstance(meal, dict):
                for option in meal.get("options", []):
                    if isinstance(option, dict):
                        points.append(_point(option, f"Day {day_number} {meal.get('meal_type', 'food')} option", "#f59e0b"))
        ordered = []
        for stop_place in day.get("route_stops", []):
            if isinstance(stop_place, dict):
                point = _point(stop_place, "route stop", "#0ea5c6")
                if point:
                    ordered.append([point["latitude"], point["longitude"]])
        if len(ordered) > 1:
            routes.append({"day": day_number, "coordinates": ordered})
    points = [point for point in points if point]
    return {"points": points, "routes": routes}


def render_itinerary_map(accommodation: dict[str, Any] | None, itinerary: list[dict[str, Any]]) -> None:
    data = itinerary_map_data(accommodation, itinerary)
    points = data["points"]
    if not points:
        return
    center = [points[0]["latitude"], points[0]["longitude"]]
    payload = json.dumps(data).replace("</", "<\\/")
    components.html(f"""
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <div id="travel-map" style="height:390px;border-radius:14px;overflow:hidden"></div>
    <div style="font:12px sans-serif;color:#334155;margin-top:4px">Dashed lines connect stops in each day's itinerary order; they are not verified road geometry.</div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
      const data = {payload};
      const points = data.points;
      const map = L.map('travel-map').setView({center}, 13);
      L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
      }}).addTo(map);
      const bounds = [];
      points.forEach((point) => {{
        L.circleMarker([point.latitude, point.longitude], {{radius: 7, color: point.color, fillOpacity: .9}})
          .addTo(map).bindPopup(`<b>${{point.name}}</b><br>${{point.kind}}<br>${{point.time || ''}}`);
        bounds.push([point.latitude, point.longitude]);
      }});
      const colors = ['#087ea4','#0ea5c6','#7c3aed','#db2777','#059669'];
      data.routes.forEach((route, index) => {{
        L.polyline(route.coordinates, {{color: colors[index % colors.length], weight: 3, dashArray: '5 7'}})
          .addTo(map).bindTooltip(`Day ${{route.day}} · stop order`);
        bounds.push(...route.coordinates);
      }});
      if (bounds.length > 1) map.fitBounds(bounds, {{padding:[20,20]}});
    </script>
    """, height=420)


def _point(place: dict[str, Any], kind: str, color: str, *, route_stop: bool = False) -> dict[str, Any] | None:
    try:
        latitude, longitude = float(place["latitude"]), float(place["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"latitude": latitude, "longitude": longitude, "name": html.escape(str(place.get("name", "Place"))), "kind": html.escape(kind), "time": html.escape(str(place.get("start_time", ""))), "color": color, "route_stop": route_stop}
