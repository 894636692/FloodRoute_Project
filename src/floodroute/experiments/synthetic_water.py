"""Controlled synthetic ponding source for offline multi-source experiments only.

Values are dimensionless indices in [0, 1].  They are not observed water levels,
water depths, or hydrodynamic predictions.
"""

from __future__ import annotations

import hashlib
import json

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import STRtree


EDGE = ["u", "v", "key"]
SOURCE = "受控模拟积涝监测源"
SOURCE_KIND = "SIMULATED_WATER_SENSOR"


def stable_seed(*parts) -> int:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % (2**32 - 1)


def static_susceptibility(edges: pd.DataFrame) -> np.ndarray:
    """Return the preregistered synthetic susceptibility, without changing static_risk."""
    def values(name):
        return pd.to_numeric(edges[name], errors="coerce").fillna(0.5).to_numpy(float)

    result = (
        0.35 * values("low_elev_norm")
        + 0.25 * values("flatness_risk")
        + 0.30 * values("builtup_frac")
        + 0.10 * (1.0 - values("vegetation_frac"))
    )
    return np.clip(result, 0, 1)


def drainage_tau(edges: pd.DataFrame) -> np.ndarray:
    """Synthetic drainage time scale in minutes, fixed before evaluation."""
    flat = pd.to_numeric(edges.flatness_risk, errors="coerce").fillna(0.5).to_numpy(float)
    built = pd.to_numeric(edges.builtup_frac, errors="coerce").fillna(0.5).to_numpy(float)
    vegetation = pd.to_numeric(edges.vegetation_frac, errors="coerce").fillna(0.5).to_numpy(float)
    return np.clip(45 + 75 * flat + 45 * built - 30 * vegetation, 30, 180)


def select_sensors(motor_edges: gpd.GeoDataFrame, seed: int = 7401) -> gpd.GeoDataFrame:
    """Select 48 sensors by 4x4 spatial cells and within-cell susceptibility thirds."""
    frame = motor_edges.copy().sort_values(EDGE).reset_index(drop=True)
    frame["static_susceptibility"] = static_susceptibility(frame)
    points = frame.geometry.interpolate(0.5, normalized=True)
    x = points.x.to_numpy(); y = points.y.to_numpy()
    xmin, ymin, xmax, ymax = frame.total_bounds
    xbin = np.minimum(((x - xmin) / max(xmax - xmin, 1e-9) * 4).astype(int), 3)
    ybin = np.minimum(((y - ymin) / max(ymax - ymin, 1e-9) * 4).astype(int), 3)
    frame["spatial_x"] = xbin; frame["spatial_y"] = ybin
    frame["_point"] = points
    rng = np.random.default_rng(seed)
    selected = []
    labels = ("low", "medium", "high")
    for iy in range(4):
        for ix in range(4):
            cell = frame[(frame.spatial_x == ix) & (frame.spatial_y == iy)].copy()
            if len(cell) < 3:
                raise ValueError(f"Spatial stratum {ix},{iy} has fewer than three motor edges")
            ranked = cell.sort_values(["static_susceptibility", *EDGE]).reset_index()
            ranked["susceptibility_band"] = pd.qcut(
                ranked.index, 3, labels=labels
            ).astype(str)
            for label in labels:
                candidates = ranked[ranked.susceptibility_band == label]
                chosen = candidates.iloc[int(rng.integers(0, len(candidates)))].copy()
                chosen["selection_stratum"] = f"cell_{ix}_{iy}_{label}"
                selected.append(chosen)
    result = gpd.GeoDataFrame(selected, geometry="_point", crs=frame.crs).reset_index(drop=True)
    result["sensor_id"] = [f"S{i:03d}" for i in range(1, len(result) + 1)]
    result["selection_seed"] = seed
    result["sensor_group"] = np.arange(len(result)) % 3
    display = result.to_crs(4326)
    result["lon"] = display.geometry.x.to_numpy(); result["lat"] = display.geometry.y.to_numpy()
    return result[["sensor_id", *EDGE, "lon", "lat", "static_susceptibility",
                   "selection_stratum", "selection_seed", "sensor_group", "_point"]]


def build_sensor_edge_mapping(edges: gpd.GeoDataFrame, sensors: gpd.GeoDataFrame,
                              radius_m: float = 1000, scale_m: float = 400) -> pd.DataFrame:
    """Precompute edge-to-sensor distance-decay links in the projected CRS."""
    edge_points = edges.geometry.interpolate(0.5, normalized=True).to_numpy()
    sensor_points = sensors.geometry.to_numpy()
    pairs = STRtree(sensor_points).query(edge_points, predicate="dwithin", distance=radius_m)
    if pairs.size == 0:
        raise ValueError("No sensor-to-edge mappings inside the registered radius")
    edge_pos, sensor_pos = pairs
    distances = np.array([
        edge_points[i].distance(sensor_points[j]) for i, j in zip(edge_pos, sensor_pos)
    ], dtype=float)
    edge_ids = edges.iloc[edge_pos][EDGE].reset_index(drop=True)
    return edge_ids.assign(
        sensor_id=sensors.iloc[sensor_pos].sensor_id.to_numpy(),
        distance_m=distances,
        spatial_weight=np.exp(-distances / scale_m),
    ).sort_values([*EDGE, "sensor_id"]).reset_index(drop=True)


def simulate_latent_ponding(edges: pd.DataFrame, rainfall_states: dict[pd.Timestamp, pd.DataFrame],
                            step_min: int = 5, inflow_gain: float = 1.35):
    """Integrate dimensionless latent ponding on every formal edge.

    ``rainfall_states`` maps 15-minute timestamps to edge frames containing a
    normalized ``value`` in [0, 1].  Returned arrays are offline truth only.
    """
    scenario_times = sorted(pd.Timestamp(t) for t in rainfall_states)
    if not scenario_times:
        raise ValueError("At least one rainfall state is required")
    index = pd.MultiIndex.from_frame(edges[EDGE])
    rain = {
        t: np.nan_to_num(rainfall_states[t].reindex(index).value.to_numpy(float), nan=0).clip(0, 1)
        for t in scenario_times
    }
    internal_times = pd.date_range(scenario_times[0], scenario_times[-1], freq=f"{step_min}min")
    susceptibility = static_susceptibility(edges)
    tau = drainage_tau(edges)
    retention = np.exp(-step_min / tau)
    water = np.zeros(len(edges), dtype=np.float32)
    states = {internal_times[0]: water.copy()}
    for previous, current in zip(internal_times[:-1], internal_times[1:]):
        forcing_time = max(t for t in scenario_times if t <= previous)
        target = inflow_gain * rain[forcing_time] * susceptibility
        water = np.clip(retention * water + (1 - retention) * target, 0, 1).astype(np.float32)
        states[current] = water.copy()
    return states


def _interpolate_state(states: dict[pd.Timestamp, np.ndarray], timestamp: pd.Timestamp) -> np.ndarray:
    times = sorted(states)
    t = pd.Timestamp(timestamp)
    if t <= times[0]: return states[times[0]].copy()
    if t >= times[-1]: return states[times[-1]].copy()
    right = next(x for x in times if x >= t)
    if right == t: return states[right].copy()
    left = times[times.index(right) - 1]
    fraction = (t - left).total_seconds() / (right - left).total_seconds()
    return ((1 - fraction) * states[left] + fraction * states[right]).astype(np.float32)


def sensor_truth_table(sensors: pd.DataFrame, edge_index: pd.MultiIndex,
                       latent_states: dict[pd.Timestamp, np.ndarray],
                       cadence_min: int = 10, offsets=(0, 3, 6)) -> pd.DataFrame:
    """Sample latent truth at asynchronous sensor schedules."""
    positions = edge_index.get_indexer(pd.MultiIndex.from_frame(sensors[EDGE]))
    if (positions < 0).any(): raise ValueError("Sensor edge missing from latent edge index")
    start, end = min(latent_states), max(latent_states)
    rows = []
    for row, position in zip(sensors.itertuples(index=False), positions):
        offset = offsets[int(row.sensor_group)]
        for timestamp in pd.date_range(start + pd.Timedelta(minutes=offset), end, freq=f"{cadence_min}min"):
            value = float(_interpolate_state(latent_states, timestamp)[position])
            rows.append({"sensor_id": row.sensor_id, "timestamp": timestamp,
                         "lon": row.lon, "lat": row.lat, "latent_ponding_truth": value,
                         "source_kind": "SIMULATED_TRUTH"})
    return pd.DataFrame(rows).sort_values(["timestamp", "sensor_id"]).reset_index(drop=True)


def observe_water(sensor_truth: pd.DataFrame, decision_time, delay_min: int, missing_rate: float,
                  noise_sigma: float, seed: int, outage_sensor_ids=(), bias_sensor_ids=(),
                  outage_start=None, outage_end=None) -> pd.DataFrame:
    """Create partial delayed observations without exposing latent truth columns."""
    if delay_min < 0 or not 0 <= missing_rate <= 1 or noise_sigma < 0:
        raise ValueError("Invalid water observation condition")
    decision = pd.Timestamp(decision_time)
    eligible = sensor_truth[pd.to_datetime(sensor_truth.timestamp).le(decision)].copy()
    rng = np.random.default_rng(seed)
    keep = rng.random(len(eligible)) >= missing_rate
    outage = eligible.sensor_id.isin(set(outage_sensor_ids))
    if outage_start is not None: outage &= pd.to_datetime(eligible.timestamp).ge(pd.Timestamp(outage_start))
    if outage_end is not None: outage &= pd.to_datetime(eligible.timestamp).le(pd.Timestamp(outage_end))
    eligible = eligible.loc[keep & ~outage].copy()
    noise = rng.normal(0, noise_sigma, len(eligible))
    bias = eligible.sensor_id.isin(set(bias_sensor_ids)).astype(float) * 0.15
    eligible["water_level_index"] = np.clip(eligible.latent_ponding_truth.to_numpy() + noise + bias, 0, 1)
    flags = np.full(len(eligible), "good", dtype=object)
    if noise_sigma >= 0.15: flags = np.char.add(flags.astype(str), ";degraded_sensor_mode")
    if delay_min >= 30: flags = np.char.add(flags.astype(str), ";communication_issue")
    if len(bias_sensor_ids):
        mask = eligible.sensor_id.isin(set(bias_sensor_ids)).to_numpy()
        flags[mask] = np.char.add(flags[mask].astype(str), ";degraded_sensor_mode")
    eligible["quality_flag"] = flags
    eligible["retrieved_at"] = pd.to_datetime(eligible.timestamp) + pd.to_timedelta(delay_min, unit="m")
    eligible["interval_min"] = 10
    eligible["source"] = SOURCE; eligible["source_kind"] = SOURCE_KIND
    eligible["source_record_id"] = [
        f"{sid}-{pd.Timestamp(ts).strftime('%Y%m%dT%H%M')}-{seed}"
        for sid, ts in zip(eligible.sensor_id, eligible.timestamp)
    ]
    columns = ["sensor_id", "timestamp", "lon", "lat", "water_level_index", "interval_min",
               "source", "quality_flag", "retrieved_at", "source_record_id", "source_kind"]
    return eligible[columns].sort_values(["timestamp", "sensor_id"]).reset_index(drop=True)


def observation_digest(observed: pd.DataFrame) -> str:
    columns = ["sensor_id", "timestamp", "water_level_index", "quality_flag", "retrieved_at"]
    normalized = observed[columns].copy().sort_values(["timestamp", "sensor_id"])
    for column in ("timestamp", "retrieved_at"):
        normalized[column] = pd.to_datetime(normalized[column], utc=True).astype(str)
    return hashlib.sha256(normalized.to_csv(index=False, lineterminator="\n").encode()).hexdigest()


def quality_penalty(flag) -> float:
    tokens = set(str(flag).lower().split(";"))
    if "sensor_outage" in tokens or "missing" in tokens: return 1.0
    if tokens & {"degraded_sensor_mode", "communication_issue", "unknown"}: return 0.5
    return 0.0


def map_water_sensors(observed: pd.DataFrame, mapping: pd.DataFrame, edges: pd.DataFrame,
                      decision_time, full_weight: float = 1.5) -> pd.DataFrame:
    """Map only observations available by decision time to the generic source frame."""
    decision = pd.Timestamp(decision_time)
    obs = observed.copy()
    obs["timestamp"] = pd.to_datetime(obs.timestamp, utc=True)
    obs["retrieved_at"] = pd.to_datetime(obs.retrieved_at, utc=True)
    obs = obs[obs.retrieved_at.le(decision)]
    obs = obs.sort_values("timestamp").groupby("sensor_id").tail(1)
    obs["age_min"] = (decision - obs.timestamp).dt.total_seconds() / 60
    obs["quality"] = obs.quality_flag.map(quality_penalty)
    joined = mapping.merge(obs[["sensor_id", "water_level_index", "age_min", "quality"]],
                           on="sensor_id", how="left", validate="many_to_one")
    valid = joined.water_level_index.notna()
    joined["valid_weight"] = joined.spatial_weight.where(valid, 0.0)
    grouped = joined.groupby(EDGE)
    sums = grouped.valid_weight.sum().rename("valid_weight").to_frame()
    for source, target in [("water_level_index", "value"), ("age_min", "age_min"), ("quality", "quality")]:
        weighted = (joined[source].fillna(0) * joined.valid_weight).groupby(
            [joined.u, joined.v, joined.key]
        ).sum()
        sums[target] = weighted / sums.valid_weight.replace(0, np.nan)
    sums["coverage"] = np.clip(sums.valid_weight / full_weight, 0, 1)
    index = pd.MultiIndex.from_frame(edges[EDGE])
    return sums[["value", "age_min", "coverage", "quality"]].reindex(index)


def build_truth_state(engine, rain_frame: pd.DataFrame, latent_water: np.ndarray,
                      weights: dict) -> pd.DataFrame:
    """Construct offline multisource truth; never pass this frame to formal methods."""
    index = engine.index
    rain = np.nan_to_num(rain_frame.reindex(index).value.to_numpy(float), nan=0).clip(0, 1)
    risk = np.clip(weights["static"] * np.asarray(engine.static, dtype=float)
                   + weights["rain_dynamic"] * rain
                   + weights["latent_water"] * np.asarray(latent_water, dtype=float), 0, 1)
    return pd.DataFrame({"risk": risk, "trusted_risk": risk, "risk_uncertainty": risk,
                         "confidence": 1.0, "freshness": 1.0, "uncertainty": 0.0}, index=index)
