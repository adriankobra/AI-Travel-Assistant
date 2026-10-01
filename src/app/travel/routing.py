"""Provider-neutral route representation. Current default intentionally has no route data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RouteEstimate:
    origin: dict[str, Any]
    destination: dict[str, Any]
    transport_mode: str | None
    distance_meters: float | None
    duration_minutes: int | None
    status: str
    source: str | None
    data_status: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class RoutingService(Protocol):
    def route(self, origin: dict[str, Any], destination: dict[str, Any], transport_mode: str | None) -> RouteEstimate: ...


class UnavailableRoutingService:
    """Safe default until a verified routing provider is selected in a later phase."""

    def route(self, origin: dict[str, Any], destination: dict[str, Any], transport_mode: str | None) -> RouteEstimate:
        return RouteEstimate(origin, destination, transport_mode, None, None, "unavailable", None, "unavailable")
