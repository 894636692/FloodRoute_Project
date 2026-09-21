"""Read-only map query and display-layer helpers.

All coordinates crossing the UI boundary are WGS84. Distance and nearest-road
operations are performed in the formal EPSG:32650 road CRS. These helpers never
change routing, risk coefficients, observations, or experiment truth data.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from floodroute.risk.freshness import freshness


def latest_rainfall(observed: pd.DataFrame, timestamp) -> pd.DataFrame:
    """Return the latest available preceding-hour observation per grid."""
    if observed.empty:
        return observed.copy()
    at = pd.Timestamp(timestamp)
    if at.tzinfo is None:
        raise ValueError("Timezone required for rainfall query")
    frame = observed.copy()
    frame["grid_id"] = frame["grid_id"].astype(str)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame[frame["timestamp"].le(at)]
    if "retrieved_at" in frame:
        available = pd.to_datetime(frame["retrieved_at"], utc=True, errors="coerce")
        frame = frame[available.isna() | available.le(at)]
    return (frame.sort_values(["timestamp", "grid_id"])
            .groupby("grid_id", as_index=False).tail(1)
            .sort_values("grid_id").reset_index(drop=True))


def nearest_grid(grids: pd.DataFrame, lon: float, lat: float) -> pd.Series:
    """Find the nearest official grid centre using a local metric approximation."""
    if grids.empty:
        raise ValueError("Grid registry is empty")
    scale_x = 111_320.0 * np.cos(np.deg2rad(lat))
    dx = (grids["lon"].to_numpy(float) - lon) * scale_x
    dy = (grids["lat"].to_numpy(float) - lat) * 110_540.0
    return grids.iloc[int(np.argmin(dx * dx + dy * dy))]


def nearest_road(runtime, lon: float, lat: float):
    """Return the nearest formal motor-road row and metric distance."""
    target = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(runtime.router.edges.crs).iloc[0]
    indices, distances = runtime.router.edges.sindex.nearest(
        target, return_all=False, return_distance=True)
    return runtime.router.edges.iloc[int(indices[1, 0])], float(distances[0])


def safe_road_name(value) -> str | None:
    text = str(value or "").strip()
    return None if not text or "�" in text else text


def _number(row, field):
    value = row.get(field, np.nan)
    return None if pd.isna(value) or not np.isfinite(float(value)) else float(value)


def build_query_result(runtime, grids: pd.DataFrame, observed: pd.DataFrame,
                       state: pd.DataFrame, mapped_rain: pd.DataFrame,
                       timestamp, lon: float, lat: float, source_kind: str,
                       road_edge_id: str | None = None) -> dict:
    """Explain available data at a clicked WGS84 location without planning.

    Terrain and land-cover fields describe the nearest formal road segment,
    which is stated explicitly in the result. Unknown values remain ``None``.
    """
    at = pd.Timestamp(timestamp)
    grid = nearest_grid(grids, lon, lat)
    rain = latest_rainfall(observed, at)
    rain_rows = rain[rain["grid_id"].eq(str(grid["grid_id"]))]
    record = rain_rows.iloc[-1] if not rain_rows.empty else None
    if road_edge_id:
        edge_tuple = tuple(map(int, road_edge_id.split(":")))
        position = runtime.router.edge_positions.get(edge_tuple)
        if position is None:
            raise ValueError("Selected display road is not in the formal road network")
        road = runtime.router.edges.iloc[position]
        target = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(runtime.router.edges.crs).iloc[0]
        road_distance = float(road.geometry.distance(target))
    else:
        road, road_distance = nearest_road(runtime, lon, lat)
    edge_id = (int(road.u), int(road.v), int(road.key))
    risk = state.loc[edge_id]
    mapped = mapped_rain.reindex(pd.MultiIndex.from_tuples([edge_id], names=["u", "v", "key"])).iloc[0]

    rain_mm = None
    rain_time = None
    rain_source = ("受控极端降雨实验（模拟，非历史实测）" if source_kind != "REAL"
                   else "深圳市气象局（台）")
    rain_age = None
    if record is not None and pd.notna(record.get("rain_mm")) and float(record["rain_mm"]) >= 0:
        rain_mm = float(record["rain_mm"])
        rain_time = pd.Timestamp(record["timestamp"]).tz_convert("Asia/Shanghai").isoformat()
        rain_age = max(0.0, (at - pd.Timestamp(record["timestamp"])).total_seconds() / 60)

    rain_risk = None
    if pd.notna(mapped.get("value")) and pd.notna(mapped.get("coverage")):
        coverage = float(np.clip(mapped["coverage"], 0, 1))
        rain_risk = float(
            np.clip(float(mapped["value"]) / runtime.config["sources"]["rain"]["scale"], 0, 1)
            * coverage
            + (1 - coverage) * runtime.config["static"]["missing_prior"]
        )

    return {
        "query_time": at.tz_convert("Asia/Shanghai").isoformat(),
        "lon": float(lon),
        "lat": float(lat),
        "grid_id": str(grid["grid_id"]),
        "grid_center_lon": float(grid["lon"]),
        "grid_center_lat": float(grid["lat"]),
        "nearest_road_distance_m": road_distance,
        "rain_mm": rain_mm,
        "rain_interval_min": 60 if rain_mm is not None else None,
        "rain_timestamp": rain_time,
        "rain_source": rain_source,
        "rain_freshness": None if rain_age is None else float(freshness(
            np.array([rain_age]), runtime.config["sources"]["rain"]["tau_min"])[0]),
        "road": {
            "edge_id": f"{edge_id[0]}:{edge_id[1]}:{edge_id[2]}",
            "name": safe_road_name(road.get("name")),
            "highway": str(road.get("highway") or "") or None,
            "length_m": _number(road, "length_m"),
            "elev_mean_m": _number(road, "elev_mean_m"),
            "elev_min_m": _number(road, "elev_min_m"),
            "slope_mean_deg": _number(road, "slope_mean_deg"),
            "low_elev_norm": _number(road, "low_elev_norm"),
            "flatness_risk": _number(road, "flatness_risk"),
            "builtup_frac": _number(road, "builtup_frac"),
            "vegetation_frac": _number(road, "vegetation_frac"),
            "water_frac": _number(road, "water_frac"),
            "static_risk": _number(risk, "static_risk"),
            "rain_risk": rain_risk,
            "risk": _number(risk, "risk"),
            "freshness": _number(risk, "freshness"),
            "uncertainty": _number(risk, "uncertainty"),
            "trusted_risk": _number(risk, "trusted_risk"),
        },
        "water_status": "真实水位数据：未启用",
        "water_reason": "当前水位数据缺少可验证的空间坐标、时间语义和测量基准，因此暂未用于道路级风险计算。",
    }


def rainfall_layer_values(observed: pd.DataFrame, timestamp) -> list[list]:
    """Compact dynamic payload: [grid_id, rain_mm, display_level]."""
    latest = latest_rainfall(observed, timestamp)
    output = []
    for row in latest.itertuples():
        value = getattr(row, "rain_mm", np.nan)
        if pd.isna(value) or float(value) < 0:
            output.append([str(row.grid_id), None, -1])
            continue
        value = float(value)
        level = 0 if value == 0 else 1 if value <= 10 else 2 if value <= 25 else 3 if value <= 50 else 4 if value <= 100 else 5
        output.append([str(row.grid_id), round(value, 3), level])
    return output


def read_display_edge_ids(path: str | Path) -> list[tuple[int, int, int]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [tuple(map(int, feature["properties"]["edge_id"].split(":")))
            for feature in data["features"]]


def road_risk_layer_values(state: pd.DataFrame, edge_ids: list[tuple[int, int, int]]) -> list[list]:
    """Compact dynamic payload; static road properties stay in the browser asset."""
    selected = state.reindex(pd.MultiIndex.from_tuples(edge_ids, names=["u", "v", "key"]))
    output = []
    for edge_id, row in selected.iterrows():
        risk = _number(row, "risk")
        level = -1 if risk is None else min(4, int(risk * 5))
        output.append([f"{edge_id[0]}:{edge_id[1]}:{edge_id[2]}",
                       None if risk is None else round(risk, 4), level])
    return output
