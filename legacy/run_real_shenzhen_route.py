"""Run route planning on the prepared real Shenzhen GIS dataset.

Real inputs:
- OSM road network
- Copernicus DEM
- ESA WorldCover 2021

Temporary scenario input:
- A simulated storm/flood field derived from low elevation, built-up land cover,
  and a storm center. Replace this part with real rainfall/water observations
  when those data are available.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import rasterio
from rasterio.transform import rowcol
from shapely.geometry import LineString


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed" / "shenzhen_core"
OUT_DIR = ROOT / "legacy" / "results" / "real_shenzhen"

# West -> east route across the small Shenzhen study area.
START_LONLAT = (114.032, 22.526)
GOAL_LONLAT = (114.078, 22.526)

RISK_WEIGHT = 5.0
TRUSTED_WEIGHT = 5.0


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalize_inverse(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return clamp((high - value) / (high - low))


def normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return clamp((value - low) / (high - low))


def landcover_risk(code: int) -> float:
    # ESA WorldCover classes. Higher means larger first-version waterlogging risk.
    return {
        10: 0.15,  # tree cover
        20: 0.25,  # shrubland
        30: 0.25,  # grassland
        40: 0.35,  # cropland
        50: 0.45,  # built-up
        60: 0.55,  # bare/sparse vegetation
        70: 0.20,  # snow/ice, not expected here
        80: 0.95,  # permanent water
        90: 0.85,  # herbaceous wetland
        95: 0.75,  # mangroves
        100: 0.30,  # moss/lichen
    }.get(code, 0.50)


def load_rasters() -> tuple[dict, dict]:
    with rasterio.open(DATA_DIR / "dem_utm_30m.tif") as dem:
        dem_arr = dem.read(1).astype("float32")
        dem_profile = {
            "transform": dem.transform,
            "bounds": dem.bounds,
            "crs": dem.crs,
            "array": dem_arr,
            "nodata": dem.nodata,
        }

    with rasterio.open(DATA_DIR / "worldcover_utm_30m_match_dem.tif") as wc:
        wc_arr = wc.read(1).astype("int16")
        wc_profile = {
            "transform": wc.transform,
            "bounds": wc.bounds,
            "crs": wc.crs,
            "array": wc_arr,
            "nodata": wc.nodata,
        }

    return dem_profile, wc_profile


def array_value(profile: dict, x: float, y: float, fallback: float = 0.0) -> float:
    arr = profile["array"]
    row, col = rowcol(profile["transform"], x, y)
    if row < 0 or col < 0 or row >= arr.shape[0] or col >= arr.shape[1]:
        return fallback
    value = float(arr[row, col])
    nodata = profile.get("nodata")
    if nodata is not None and value == nodata:
        return fallback
    return value


def nearest_node(nodes: gpd.GeoDataFrame, lon: float, lat: float) -> int:
    target = gpd.GeoSeries.from_xy([lon], [lat], crs="EPSG:4326").to_crs(nodes.crs).iloc[0]
    distances = nodes.geometry.distance(target)
    return int(nodes.loc[distances.idxmin(), "osmid"])


def build_graph_and_scores() -> tuple[nx.Graph, gpd.GeoDataFrame, gpd.GeoDataFrame, dict]:
    nodes = gpd.read_file(DATA_DIR / "osm_nodes_utm.geojson")
    edges = gpd.read_file(DATA_DIR / "osm_edges_utm.geojson")
    dem, wc = load_rasters()

    valid_dem = dem["array"]
    valid_dem = valid_dem[valid_dem > -1000]
    elev_p05, elev_p95 = np.percentile(valid_dem, [5, 95])

    grad_y, grad_x = np.gradient(dem["array"], 30.0, 30.0)
    slope = np.sqrt(grad_x**2 + grad_y**2)
    slope_p95 = np.percentile(slope[np.isfinite(slope)], 95)
    dem["slope"] = slope

    # Storm center near the middle of the study area. This creates a reproducible
    # flood scenario until real rainfall/water observations are connected.
    minx, miny, maxx, maxy = nodes.total_bounds
    center_x = (minx + maxx) / 2
    center_y = (miny + maxy) / 2
    storm_radius = 1200.0

    scores: dict[int, dict[str, float]] = {}
    for _, row in nodes.iterrows():
        osmid = int(row["osmid"])
        x = float(row.geometry.x)
        y = float(row.geometry.y)

        elev = array_value(dem, x, y, fallback=float(elev_p95))
        wc_code = int(array_value(wc, x, y, fallback=50))
        row_idx, col_idx = rowcol(dem["transform"], x, y)
        if 0 <= row_idx < slope.shape[0] and 0 <= col_idx < slope.shape[1]:
            slope_value = float(slope[row_idx, col_idx])
        else:
            slope_value = slope_p95

        low_elevation = normalize_inverse(elev, float(elev_p05), float(elev_p95))
        low_slope_risk = 1.0 - normalize(slope_value, 0.0, float(slope_p95))
        cover_risk = landcover_risk(wc_code)

        distance_to_storm = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
        storm = max(0.0, 1.0 - distance_to_storm / storm_radius)

        rainfall_truth = clamp(0.25 + 0.65 * storm)
        water_truth = clamp(
            0.05
            + 0.50 * low_elevation
            + 0.15 * cover_risk
            + 0.25 * storm
        )

        sensitive = water_truth >= 0.45 or storm >= 0.35
        if sensitive:
            rainfall_observed = rainfall_truth * 0.35
            water_observed = water_truth * 0.30
            age = 120.0
            uncertainty = 0.90
            sensitivity = 1.0
        else:
            rainfall_observed = rainfall_truth
            water_observed = water_truth
            age = 15.0
            uncertainty = 0.15
            sensitivity = 0.05

        static_risk = clamp(0.55 * low_elevation + 0.25 * low_slope_risk + 0.20 * cover_risk)
        observed_risk = clamp(static_risk + 0.20 * rainfall_observed + 0.20 * water_observed)
        true_risk = clamp(static_risk + 0.20 * rainfall_truth + 0.20 * water_truth)
        freshness = np.exp(-age / 30.0)
        trusted_risk = clamp(observed_risk + 1.5 * uncertainty * sensitivity + 2.0 * (1 - freshness) * sensitivity)

        scores[osmid] = {
            "elevation": elev,
            "worldcover": wc_code,
            "low_elevation": low_elevation,
            "slope_risk": low_slope_risk,
            "landcover": cover_risk,
            "rainfall_truth": rainfall_truth,
            "water_truth": water_truth,
            "rainfall_observed": rainfall_observed,
            "water_observed": water_observed,
            "age_minutes": age,
            "uncertainty": uncertainty,
            "sensitivity": sensitivity,
            "observed_risk": observed_risk,
            "true_risk": true_risk,
            "trusted_risk": trusted_risk,
            "x": x,
            "y": y,
        }

    graph = nx.Graph()
    graph.add_nodes_from(scores)
    for _, row in edges.iterrows():
        u = int(row["u"])
        v = int(row["v"])
        if u not in scores or v not in scores:
            continue
        length = float(row.get("length") or row.geometry.length)
        if graph.has_edge(u, v) and graph[u][v]["length"] <= length:
            continue
        graph.add_edge(
            u,
            v,
            length=length,
            geometry=row.geometry,
            shortest_cost=length,
            risk_cost=length * (1.0 + RISK_WEIGHT * (scores[u]["observed_risk"] + scores[v]["observed_risk"]) / 2.0),
            trusted_cost=length * (1.0 + TRUSTED_WEIGHT * (scores[u]["trusted_risk"] + scores[v]["trusted_risk"]) / 2.0),
        )

    return graph, nodes, edges, scores


def route_metrics(path: list[int], graph: nx.Graph, scores: dict[int, dict[str, float]]) -> dict[str, float]:
    length = 0.0
    for u, v in zip(path[:-1], path[1:]):
        length += graph[u][v]["length"]
    true_risks = [scores[node]["true_risk"] for node in path]
    observed_risks = [scores[node]["observed_risk"] for node in path]
    trusted_risks = [scores[node]["trusted_risk"] for node in path]
    return {
        "length_m": round(length, 1),
        "nodes": len(path),
        "observed_risk_mean": round(float(np.mean(observed_risks)), 4),
        "true_risk_mean": round(float(np.mean(true_risks)), 4),
        "true_risk_max": round(float(np.max(true_risks)), 4),
        "trusted_risk_mean": round(float(np.mean(trusted_risks)), 4),
        "high_true_risk_nodes": int(sum(r >= 0.75 for r in true_risks)),
    }


def route_lines(path: list[int], graph: nx.Graph, scores: dict[int, dict[str, float]]) -> list[LineString]:
    lines = []
    for u, v in zip(path[:-1], path[1:]):
        geometry = graph[u][v].get("geometry")
        if geometry is None:
            geometry = LineString([(scores[u]["x"], scores[u]["y"]), (scores[v]["x"], scores[v]["y"])])
        lines.append(geometry)
    return lines


def save_csv(scores: dict[int, dict[str, float]], graph: nx.Graph) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nodes_path = OUT_DIR / "real_nodes_sampled.csv"
    edges_path = OUT_DIR / "real_edges_sampled.csv"

    with nodes_path.open("w", newline="", encoding="utf-8-sig") as file:
        fieldnames = ["osmid"] + list(next(iter(scores.values())).keys())
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for osmid, values in scores.items():
            writer.writerow({"osmid": osmid, **values})

    with edges_path.open("w", newline="", encoding="utf-8-sig") as file:
        fieldnames = ["u", "v", "length", "shortest_cost", "risk_cost", "trusted_cost"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for u, v, values in graph.edges(data=True):
            writer.writerow({key: values[key] for key in fieldnames if key in values} | {"u": u, "v": v})


def plot_result(edges: gpd.GeoDataFrame, routes: dict[str, list[int]], graph: nx.Graph, scores: dict[int, dict[str, float]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 9), dpi=160)
    edges.plot(ax=ax, color="#d6d6d6", linewidth=0.45)

    styles = {
        "shortest": ("#222222", "--", "Shortest"),
        "risk": ("#1f77b4", "-", "Observed-risk route"),
        "trusted": ("#138a36", "-", "Trusted route"),
    }
    for name, path in routes.items():
        gdf = gpd.GeoDataFrame(geometry=route_lines(path, graph, scores), crs=edges.crs)
        color, linestyle, label = styles[name]
        gdf.plot(ax=ax, color=color, linewidth=2.4, linestyle=linestyle, label=label)

    start = routes["shortest"][0]
    goal = routes["shortest"][-1]
    ax.scatter(scores[start]["x"], scores[start]["y"], c="black", s=80, marker="o", label="Start")
    ax.scatter(scores[goal]["x"], scores[goal]["y"], c="black", s=120, marker="*", label="Goal")
    ax.set_title("Shenzhen real GIS route test: OSM + DEM + WorldCover")
    ax.set_axis_off()
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "real_route_comparison.png")
    plt.close(fig)


def save_routes_geojson(routes: dict[str, list[int]], graph: nx.Graph, scores: dict[int, dict[str, float]]) -> None:
    features = []
    for name, path in routes.items():
        for order, geometry in enumerate(route_lines(path, graph, scores)):
            features.append(
                {
                    "route": name,
                    "order": order,
                    "geometry": geometry,
                }
            )
    gdf = gpd.GeoDataFrame(features, geometry="geometry", crs="EPSG:32650")
    gdf.to_file(OUT_DIR / "real_routes_utm.geojson", driver="GeoJSON")
    gdf.to_crs("EPSG:4326").to_file(OUT_DIR / "real_routes_wgs84.geojson", driver="GeoJSON")


def main() -> None:
    graph, nodes, edges, scores = build_graph_and_scores()
    start = nearest_node(nodes, *START_LONLAT)
    goal = nearest_node(nodes, *GOAL_LONLAT)

    routes = {
        "shortest": nx.shortest_path(graph, start, goal, weight="shortest_cost"),
        "risk": nx.shortest_path(graph, start, goal, weight="risk_cost"),
        "trusted": nx.shortest_path(graph, start, goal, weight="trusted_cost"),
    }
    metrics = {
        name: route_metrics(path, graph, scores)
        for name, path in routes.items()
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "real_route_metrics.json").write_text(
        json.dumps(
            {
                "start_osmid": start,
                "goal_osmid": goal,
                "start_lonlat": START_LONLAT,
                "goal_lonlat": GOAL_LONLAT,
                "note": "OSM/DEM/WorldCover are real. Rainfall/water scenario is simulated until observations are connected.",
                "metrics": metrics,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    save_csv(scores, graph)
    plot_result(edges, routes, graph, scores)
    save_routes_geojson(routes, graph, scores)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"saved: {OUT_DIR}")


if __name__ == "__main__":
    main()
