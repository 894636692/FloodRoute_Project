"""Static, dynamic, freshness, uncertainty, and trusted-risk models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import math

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from floodroute.common.config import FloodRouteConfig
from floodroute.common.schema import (
    CALCULATION_CRS,
    RAINFALL_REQUIRED_FIELDS,
    ROAD_STATIC_REQUIRED_FIELDS,
    WATER_LEVEL_REQUIRED_FIELDS,
    parse_iso8601,
)


def clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass
class EdgeState:
    u: int
    v: int
    key: int
    static_risk: float
    rain_risk: float
    water_risk: float
    risk: float
    rain_age_min: float
    water_age_min: float
    rain_freshness: float
    water_freshness: float
    uncertainty: float
    confidence: float
    trusted_risk: float
    timestamp: str

    @property
    def edge_id(self) -> tuple[int, int, int]:
        return (self.u, self.v, self.key)

    def to_dict(self) -> dict:
        return asdict(self)


def validate_static_edges(edges: gpd.GeoDataFrame) -> None:
    missing = sorted(ROAD_STATIC_REQUIRED_FIELDS - set(edges.columns))
    if missing:
        raise ValueError(f"road_static_features missing fields: {', '.join(missing)}")
    if str(edges.crs) != CALCULATION_CRS:
        raise ValueError(f"road_static_features CRS must be {CALCULATION_CRS}, got {edges.crs}")


class StaticRiskModel:
    def __init__(self, config: FloodRouteConfig | None = None) -> None:
        self.config = config or FloodRouteConfig()

    def score(self, row: pd.Series) -> float:
        weights = self.config.static_weights
        vegetation_relief = 1.0 - clamp(row.get("vegetation_frac", 0.0))
        return clamp(
            weights.low_elevation * clamp(row["low_elev_norm"])
            + weights.flatness * clamp(row["flatness_risk"])
            + weights.builtup * clamp(row["builtup_frac"])
            + weights.water * clamp(row["water_frac"])
            + weights.vegetation_relief * vegetation_relief
        )


class DynamicObservationMatcher:
    """Map C-standardized station observations to road edges.

    This class consumes already-standardized CSVs. It does not call government
    APIs or parse raw source formats.
    """

    def __init__(self, config: FloodRouteConfig | None = None) -> None:
        self.config = config or FloodRouteConfig()

    def _latest_observations(
        self,
        csv_path: str | None,
        required_fields: set[str],
        value_field: str,
        timestamp: datetime,
    ) -> gpd.GeoDataFrame | None:
        if not csv_path:
            return None
        frame = pd.read_csv(csv_path)
        missing = sorted(required_fields - set(frame.columns))
        if missing:
            raise ValueError(f"{csv_path} missing fields: {', '.join(missing)}")
        if frame.empty:
            return None

        frame["parsed_timestamp"] = frame["timestamp"].map(lambda value: parse_iso8601(str(value)))
        frame = frame[frame["parsed_timestamp"] <= timestamp]
        if frame.empty:
            return None
        frame = frame.sort_values("parsed_timestamp").groupby("station_id", as_index=False).tail(1)
        geometry = [Point(float(row.lon), float(row.lat)) for row in frame.itertuples()]
        gdf = gpd.GeoDataFrame(frame, geometry=geometry, crs="EPSG:4326").to_crs(CALCULATION_CRS)
        gdf[value_field] = pd.to_numeric(gdf[value_field], errors="coerce")
        return gdf.dropna(subset=[value_field])

    def _nearest_for_edge(
        self,
        edge_geometry,
        observations: gpd.GeoDataFrame | None,
        value_field: str,
        timestamp: datetime,
    ) -> tuple[float, float, float, str]:
        if observations is None or observations.empty:
            return 0.0, 10_000.0, 9999.0, "missing"
        centroid = edge_geometry.interpolate(0.5, normalized=True)
        distances = observations.geometry.distance(centroid)
        idx = distances.idxmin()
        row = observations.loc[idx]
        value = float(row[value_field])
        distance_m = float(distances.loc[idx])
        age_min = max(0.0, (timestamp - row["parsed_timestamp"]).total_seconds() / 60.0)
        quality = str(row.get("quality_flag", "unknown"))
        return value, distance_m, age_min, quality

    def attach_dynamic(
        self,
        edges: gpd.GeoDataFrame,
        timestamp: str,
        rainfall_csv: str | None = None,
        water_level_csv: str | None = None,
    ) -> pd.DataFrame:
        request_time = parse_iso8601(timestamp)
        rainfall = self._latest_observations(
            rainfall_csv, RAINFALL_REQUIRED_FIELDS, "rain_mm", request_time
        )
        water = self._latest_observations(
            water_level_csv, WATER_LEVEL_REQUIRED_FIELDS, "water_level_cm", request_time
        )
        rows = []
        for row in edges.itertuples():
            rain_mm, rain_distance, rain_age, rain_quality = self._nearest_for_edge(
                row.geometry, rainfall, "rain_mm", request_time
            )
            water_cm, water_distance, water_age, water_quality = self._nearest_for_edge(
                row.geometry, water, "water_level_cm", request_time
            )
            rows.append(
                {
                    "u": int(row.u),
                    "v": int(row.v),
                    "key": int(row.key),
                    "rain_mm": rain_mm,
                    "rain_distance_m": rain_distance,
                    "rain_age_min": rain_age,
                    "rain_quality_flag": rain_quality,
                    "water_level_cm": water_cm,
                    "water_distance_m": water_distance,
                    "water_age_min": water_age,
                    "water_quality_flag": water_quality,
                }
            )
        return pd.DataFrame(rows)


class EdgeRiskEngine:
    def __init__(self, config: FloodRouteConfig | None = None) -> None:
        self.config = config or FloodRouteConfig()
        self.static_model = StaticRiskModel(self.config)

    def _freshness(self, age_min: float, tau_min: float) -> float:
        if age_min >= 9999:
            return 0.0
        return clamp(math.exp(-max(0.0, age_min) / tau_min))

    def _uncertainty(
        self,
        rain_distance_m: float,
        water_distance_m: float,
        rain_quality: str,
        water_quality: str,
    ) -> float:
        cfg = self.config.uncertainty
        distance_component = min(rain_distance_m, water_distance_m) / cfg.distance_scale_m
        quality_penalty = 0.0
        for flag in (rain_quality, water_quality):
            lowered = str(flag).lower()
            if lowered in {"bad", "invalid", "suspect", "missing"}:
                quality_penalty += cfg.bad_quality_penalty
            elif lowered == "unknown":
                quality_penalty += cfg.missing_penalty / 2
        return clamp(cfg.base + distance_component + quality_penalty)

    def build_edge_states(
        self,
        static_edges: gpd.GeoDataFrame,
        timestamp: str,
        dynamic_frame: pd.DataFrame | None = None,
    ) -> dict[tuple[int, int, int], EdgeState]:
        validate_static_edges(static_edges)
        dynamic_lookup = {}
        if dynamic_frame is not None and not dynamic_frame.empty:
            for row in dynamic_frame.itertuples():
                dynamic_lookup[(int(row.u), int(row.v), int(row.key))] = row._asdict()

        states = {}
        for row in static_edges.itertuples():
            edge_id = (int(row.u), int(row.v), int(row.key))
            dyn = dynamic_lookup.get(edge_id, {})
            static_risk = self.static_model.score(pd.Series(row._asdict()))
            rain_risk = clamp(float(dyn.get("rain_mm", 0.0)) / 80.0)
            water_risk = clamp(float(dyn.get("water_level_cm", 0.0)) / 80.0)
            rain_age = float(dyn.get("rain_age_min", 9999.0))
            water_age = float(dyn.get("water_age_min", 9999.0))
            rain_freshness = self._freshness(rain_age, self.config.freshness.rain_tau_min)
            water_freshness = self._freshness(water_age, self.config.freshness.water_tau_min)
            uncertainty = self._uncertainty(
                float(dyn.get("rain_distance_m", 10_000.0)),
                float(dyn.get("water_distance_m", 10_000.0)),
                str(dyn.get("rain_quality_flag", "missing")),
                str(dyn.get("water_quality_flag", "missing")),
            )

            dw = self.config.dynamic_weights
            risk = clamp(dw.static * static_risk + dw.rain * rain_risk + dw.water * water_risk)
            tc = self.config.trusted
            trusted_risk = clamp(
                risk
                + tc.uncertainty_weight * uncertainty
                + tc.rain_staleness_weight * (1.0 - rain_freshness)
                + tc.water_staleness_weight * (1.0 - water_freshness)
            )
            confidence = clamp((rain_freshness + water_freshness) / 2.0 * (1.0 - uncertainty))
            states[edge_id] = EdgeState(
                u=edge_id[0],
                v=edge_id[1],
                key=edge_id[2],
                static_risk=static_risk,
                rain_risk=rain_risk,
                water_risk=water_risk,
                risk=risk,
                rain_age_min=rain_age,
                water_age_min=water_age,
                rain_freshness=rain_freshness,
                water_freshness=water_freshness,
                uncertainty=uncertainty,
                confidence=confidence,
                trusted_risk=trusted_risk,
                timestamp=timestamp,
            )
        return states

