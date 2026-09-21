"""Pre-registered expanded scenarios over real Shenzhen grid geometry.

This offline module owns latent truth.  Routing receives only RiskEngine output
derived from perturbed observations and never imports this generator.
"""

from __future__ import annotations

import hashlib
import json

import networkx as nx
import numpy as np
import pandas as pd


FAMILIES = ("moving_center", "dual_center", "anisotropic_band")
AMPLITUDES = np.array([8, 15, 28, 45, 70, 100, 125, 145, 150, 135, 105, 75], dtype=float)


def stable_seed(*parts) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def generate_family_truth(grids, domain_bounds, family: str, seed: int, start: str) -> pd.DataFrame:
    """Generate one of three fixed spatial stress fields on real grid cells."""
    if family not in FAMILIES:
        raise ValueError(f"Unknown family: {family}")
    cells = grids.sort_values("grid_id").reset_index(drop=True)
    centres = cells.geometry.centroid
    xmin, ymin, xmax, ymax = map(float, domain_bounds)
    x = (centres.x.to_numpy() - xmin) / (xmax - xmin)
    y = (centres.y.to_numpy() - ymin) / (ymax - ymin)
    rng = np.random.default_rng(seed)
    heterogeneity = rng.uniform(0.95, 1.05, len(cells))
    times = pd.date_range(start, periods=12, freq="15min")
    rows = []
    for step, (timestamp, amplitude) in enumerate(zip(times, AMPLITUDES)):
        phase = step / 11
        if family == "moving_center":
            cx, cy = -0.05 + 1.10 * phase, 0.05 + 0.90 * phase
            field = np.exp(-0.5 * (((x - cx) / 0.13) ** 2 + ((y - cy) / 0.13) ** 2))
        elif family == "dual_center":
            c1 = (0.28 + 0.06 * np.sin(np.pi * phase), 0.72 - 0.10 * phase)
            c2 = (0.75 - 0.08 * phase, 0.25 + 0.12 * phase)
            first = np.exp(-0.5 * (((x - c1[0]) / 0.15) ** 2 + ((y - c1[1]) / 0.13) ** 2))
            second = np.exp(-0.5 * (((x - c2[0]) / 0.14) ** 2 + ((y - c2[1]) / 0.16) ** 2))
            field = np.maximum((0.75 + 0.25 * (1 - phase)) * first, (0.65 + 0.35 * phase) * second)
        else:
            angle = np.deg2rad(25 + 20 * phase)
            cx, cy = 0.18 + 0.64 * phase, 0.50
            along = (x - cx) * np.cos(angle) + (y - cy) * np.sin(angle)
            across = -(x - cx) * np.sin(angle) + (y - cy) * np.cos(angle)
            field = np.exp(-0.5 * ((along / 0.48) ** 2 + (across / 0.085) ** 2))
        rain = 2.0 + amplitude * field * heterogeneity
        rows.append(pd.DataFrame({
            "grid_id": cells.grid_id.astype(str),
            "timestamp": timestamp,
            "window_start": timestamp - pd.Timedelta(hours=1),
            "rain_mm": rain,
            "interval_min": 60,
            "quality_flag": "simulated_expanded_validation",
            "scenario_family": family,
            "random_seed": seed,
        }))
    return pd.concat(rows, ignore_index=True)


def observation_digest(frame: pd.DataFrame) -> str:
    columns = ["grid_id", "timestamp", "rain_mm"]
    stable = frame[columns].copy().sort_values(["grid_id", "timestamp"])
    stable["timestamp"] = pd.to_datetime(stable.timestamp, utc=True).astype(str)
    payload = stable.to_csv(index=False, lineterminator="\n", float_format="%.12g").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def route_digest(edge_ids) -> str:
    return hashlib.sha256(json.dumps([list(map(int, edge)) for edge in edge_ids]).encode("utf-8")).hexdigest()


def route_overlap(route, shortest, lengths: pd.Series) -> float:
    left, right = set(route.edge_ids), set(shortest.edge_ids)
    union = left | right
    if not union:
        return 1.0
    intersection_length = sum(float(lengths.loc[edge]) for edge in left & right)
    union_length = sum(float(lengths.loc[edge]) for edge in union)
    return intersection_length / union_length


def select_od_pairs(runtime, count: int = 8, seed: int = 7201) -> pd.DataFrame:
    """Deterministic spatial/directional sampling without any risk outcomes."""
    graph = runtime.router.graph
    component = max(nx.weakly_connected_components(graph), key=len)
    nodes = runtime.router.nodes[runtime.router.nodes.osmid.isin(component)].copy()
    nodes = nodes.set_index("osmid", drop=False)
    xmid, ymid = nodes.geometry.x.median(), nodes.geometry.y.median()
    directions = [
        ("E", (-1, 0), (1, 0)), ("W", (1, 0), (-1, 0)),
        ("N", (0, -1), (0, 1)), ("S", (0, 1), (0, -1)),
        ("NE", (-1, -1), (1, 1)), ("SW", (1, 1), (-1, -1)),
        ("NW", (1, -1), (-1, 1)), ("SE", (-1, 1), (1, -1)),
    ]
    rng = np.random.default_rng(seed)
    used = set(); rows = []
    node_xy = {int(r.osmid): (float(r.geometry.x), float(r.geometry.y)) for r in nodes.itertuples()}
    for index, (name, start_side, vector) in enumerate(directions[:count], start=1):
        sx, sy = start_side
        mask_x = nodes.geometry.x.le(xmid) if sx < 0 else nodes.geometry.x.ge(xmid) if sx > 0 else pd.Series(True, index=nodes.index)
        mask_y = nodes.geometry.y.le(ymid) if sy < 0 else nodes.geometry.y.ge(ymid) if sy > 0 else pd.Series(True, index=nodes.index)
        starts = nodes.loc[mask_x & mask_y, "osmid"].astype(int).to_numpy()
        starts = rng.permutation(np.sort(starts))
        chosen = None
        for start_node in starts[:600]:
            if int(start_node) in used:
                continue
            distances = nx.single_source_dijkstra_path_length(graph, int(start_node), cutoff=15000, weight="length_m")
            start_xy = node_xy[int(start_node)]
            eligible = []
            vector_norm = np.hypot(*vector)
            for goal_node, distance in distances.items():
                goal_node = int(goal_node)
                if not 3000 <= distance <= 15000 or goal_node in used or goal_node == int(start_node):
                    continue
                dx, dy = node_xy[goal_node][0] - start_xy[0], node_xy[goal_node][1] - start_xy[1]
                norm = np.hypot(dx, dy)
                if norm and (dx * vector[0] + dy * vector[1]) / (norm * vector_norm) >= 0.55:
                    eligible.append(goal_node)
            if eligible:
                goal_node = int(rng.permutation(np.sort(eligible))[0])
                chosen = (int(start_node), goal_node, float(distances[goal_node]))
                break
        if chosen is None:
            raise RuntimeError(f"Could not find protocol-compliant OD for direction {name}")
        start_node, goal_node, distance = chosen
        used.update([start_node, goal_node])
        rows.append({
            "od_id": f"OD{index:02d}", "direction": name,
            "start_node": start_node, "goal_node": goal_node,
            "start_x": node_xy[start_node][0], "start_y": node_xy[start_node][1],
            "goal_x": node_xy[goal_node][0], "goal_y": node_xy[goal_node][1],
            "shortest_distance_m": distance, "selection_seed": seed,
        })
    frame = pd.DataFrame(rows)
    points = runtime.router.nodes.set_index("osmid").loc[
        list(frame.start_node) + list(frame.goal_node)
    ].to_crs(4326).geometry
    n = len(frame)
    frame["start_lon"] = [float(p.x) for p in points.iloc[:n]]
    frame["start_lat"] = [float(p.y) for p in points.iloc[:n]]
    frame["goal_lon"] = [float(p.x) for p in points.iloc[n:]]
    frame["goal_lat"] = [float(p.y) for p in points.iloc[n:]]
    return frame[[
        "od_id", "direction", "start_node", "goal_node", "start_lon", "start_lat",
        "goal_lon", "goal_lat", "shortest_distance_m", "selection_seed",
    ]]
