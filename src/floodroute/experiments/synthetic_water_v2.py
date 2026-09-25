"""V2 controlled ponding truth with independent latent local hydrologic state.

Everything in this module is simulated.  Values are dimensionless indices and
must never be described as real Shenzhen drainage capacity or water depth.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .synthetic_water import EDGE, drainage_tau, stable_seed, static_susceptibility


def _edge_points(edges):
    points = edges.geometry.interpolate(.5, normalized=True)
    x = points.x.to_numpy(float); y = points.y.to_numpy(float)
    xmin, ymin, xmax, ymax = edges.total_bounds
    return (x - xmin) / max(xmax - xmin, 1e-9), (y - ymin) / max(ymax - ymin, 1e-9)


def local_hydrologic_state(edges, seed: int = 9401, anchor_count: int = 12,
                           length_scale: float = .18) -> np.ndarray:
    """Create an OD- and route-independent spatial low-frequency latent field."""
    if anchor_count < 2 or length_scale <= 0:
        raise ValueError("Invalid latent field parameters")
    x, y = _edge_points(edges)
    rng = np.random.default_rng(seed)
    anchors = rng.uniform(0, 1, size=(anchor_count, 2))
    amplitude = rng.normal(0, 1, anchor_count)
    field = np.zeros(len(edges), dtype=float)
    normalizer = np.zeros(len(edges), dtype=float)
    for (ax, ay), value in zip(anchors, amplitude):
        weight = np.exp(-((x - ax) ** 2 + (y - ay) ** 2) / (2 * length_scale**2))
        field += weight * value; normalizer += weight
    field /= np.maximum(normalizer, 1e-12)
    # Fixed rank transform gives a reproducible [0,1] field without outcome tuning.
    return pd.Series(field).rank(method="average", pct=True).to_numpy(float)


def event_disturbance(edges, scenario_family: str, seed: int, timestamps,
                      min_patches: int = 1, max_patches: int = 3):
    """Generate spatially correlated transient disturbance patches.

    Patch locations depend only on scenario family and seed; no OD, route or
    performance input is accepted by this API.
    """
    times = [pd.Timestamp(t) for t in timestamps]
    if not times or min_patches < 1 or max_patches < min_patches:
        raise ValueError("Invalid disturbance parameters")
    x, y = _edge_points(edges)
    rng = np.random.default_rng(stable_seed("v2_disturbance", scenario_family, seed))
    count = int(rng.integers(min_patches, max_patches + 1))
    patches = []
    for patch_id in range(count):
        start = int(rng.integers(2, 6)); duration = int(rng.integers(3, 6)); recovery = 2
        patches.append({
            "patch_id": patch_id + 1, "center_x": float(rng.uniform(.08, .92)),
            "center_y": float(rng.uniform(.08, .92)), "width": float(rng.uniform(.06, .14)),
            "amplitude": float(rng.uniform(.55, 1.0)), "start_step": start,
            "duration_steps": duration, "recovery_steps": recovery,
        })
    states = {}
    for step, timestamp in enumerate(times):
        value = np.zeros(len(edges), dtype=float)
        for patch in patches:
            end = patch["start_step"] + patch["duration_steps"]
            if step < patch["start_step"]:
                temporal = 0.
            elif step < end:
                temporal = 1.
            elif step < end + patch["recovery_steps"]:
                temporal = 1 - (step - end + 1) / (patch["recovery_steps"] + 1)
            else:
                temporal = 0.
            spatial = np.exp(-((x - patch["center_x"]) ** 2 + (y - patch["center_y"]) ** 2) / (2 * patch["width"]**2))
            value = np.maximum(value, patch["amplitude"] * temporal * spatial)
        states[timestamp] = np.clip(value, 0, 1).astype(np.float32)
    return states, pd.DataFrame(patches)


def simulate_latent_ponding_v2(edges, rainfall_states, scenario_family: str, seed: int,
                               local_seed: int = 9401, step_min: int = 5,
                               inflow_gain: float = 1.35):
    """Integrate V2 ponding with latent local state and transient disturbances."""
    scenario_times = sorted(pd.Timestamp(t) for t in rainfall_states)
    if not scenario_times:
        raise ValueError("At least one rainfall state is required")
    index = pd.MultiIndex.from_frame(edges[EDGE])
    rain = {t: np.nan_to_num(rainfall_states[t].reindex(index).value.to_numpy(float), nan=0).clip(0, 1) for t in scenario_times}
    local = local_hydrologic_state(edges, local_seed)
    disturbance_15m, patches = event_disturbance(edges, scenario_family, seed, scenario_times)
    internal_times = pd.date_range(scenario_times[0], scenario_times[-1], freq=f"{step_min}min")
    susceptibility = static_susceptibility(edges); base_tau = drainage_tau(edges)
    water = np.zeros(len(edges), dtype=np.float32); states = {internal_times[0]: water.copy()}
    disturbance_states = {internal_times[0]: disturbance_15m[scenario_times[0]].copy()}
    for previous, current in zip(internal_times[:-1], internal_times[1:]):
        forcing_time = max(t for t in scenario_times if t <= previous)
        disturbance = disturbance_15m[forcing_time].astype(float)
        # A broad, smooth multiplier is required for the hidden local state to
        # remain observable after conditioning on rain and known static risk.
        # These coefficients were fixed during the pre-confirmatory mechanism
        # check; they were not selected from any route outcome.
        tau = np.clip(base_tau * (.35 + 2.50 * local + 1.20 * disturbance), 15, 360)
        retention = np.exp(-step_min / tau)
        # Regional rain supplies a catchment-scale forcing.  H and B modulate
        # local convergence/retention, so two edges with similar local rain and
        # known static susceptibility can still have different ponding states.
        # The upper-decile regional forcing represents rain available for
        # neighbourhood runoff convergence; it is a deterministic event
        # summary, not a route- or outcome-selected value.
        regional_forcing = float(np.quantile(rain[forcing_time], .90))
        target = np.clip(inflow_gain * (
            .55 * rain[forcing_time] * susceptibility
            + .90 * regional_forcing * local
            + .65 * regional_forcing * disturbance
        ), 0, 1)
        water = np.clip(retention * water + (1 - retention) * target, 0, 1).astype(np.float32)
        states[current] = water.copy(); disturbance_states[current] = disturbance.astype(np.float32)
    metadata = {
        "local_hydrologic_state": local,
        "disturbance_states": disturbance_states,
        "patches": patches,
        "source_kind": "SIMULATED_WATER_SENSOR_V2",
        "truth_kind": "SIMULATED_TRUTH_V2",
    }
    return states, metadata

