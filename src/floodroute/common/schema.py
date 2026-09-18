"""Frozen interfaces shared by A, B, and C.

This module intentionally contains simple constants and validation helpers.
The planning document is a reference, but these constants are the executable
contract used by B's code and tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


CALCULATION_CRS = "EPSG:32650"
DISPLAY_CRS = "EPSG:4326"

ROAD_STATIC_REQUIRED_FIELDS = {
    "u",
    "v",
    "key",
    "length_m",
    "elev_mean_m",
    "elev_min_m",
    "low_elev_norm",
    "slope_mean_deg",
    "flatness_risk",
    "builtup_frac",
    "vegetation_frac",
    "water_frac",
    "source_version",
    "geometry",
}

RAINFALL_REQUIRED_FIELDS = {
    "station_id",
    "timestamp",
    "lon",
    "lat",
    "rain_mm",
    "source",
    "retrieved_at",
    "quality_flag",
}

WATER_LEVEL_REQUIRED_FIELDS = {
    "station_id",
    "timestamp",
    "lon",
    "lat",
    "water_level_cm",
    "source",
    "retrieved_at",
    "quality_flag",
}

ROUTE_REQUEST_REQUIRED_FIELDS = {
    "start_lon",
    "start_lat",
    "goal_lon",
    "goal_lat",
    "timestamp",
    "mode",
}


def parse_iso8601(value: str) -> datetime:
    """Parse ISO 8601 timestamps and require timezone info."""

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {value}")
    return parsed


def require_fields(data: dict[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"{label} missing required fields: {', '.join(missing)}")


@dataclass(frozen=True)
class RouteRequest:
    start_lon: float
    start_lat: float
    goal_lon: float
    goal_lat: float
    timestamp: str
    mode: str = "trusted"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RouteRequest":
        require_fields(data, ROUTE_REQUEST_REQUIRED_FIELDS, "route request")
        parse_iso8601(str(data["timestamp"]))
        mode = str(data["mode"])
        if mode not in {"shortest", "risk", "trusted"}:
            raise ValueError("mode must be one of: shortest, risk, trusted")
        return cls(
            start_lon=float(data["start_lon"]),
            start_lat=float(data["start_lat"]),
            goal_lon=float(data["goal_lon"]),
            goal_lat=float(data["goal_lat"]),
            timestamp=str(data["timestamp"]),
            mode=mode,
        )

