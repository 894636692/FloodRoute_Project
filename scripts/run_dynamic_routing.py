from __future__ import annotations

import csv
import heapq
import json
import math
from pathlib import Path

import numpy as np
from osgeo import gdal


ROOT = Path(r"D:\LaotuZhBi\laotu-data")
STATIC = ROOT / "data" / "processed" / "static_risk"
DYNAMIC = ROOT / "data" / "processed" / "dynamic_risk"
ROUTING = DYNAMIC / "routing"
ROUTING.mkdir(parents=True, exist_ok=True)

ROADS_STATIC = STATIC / "roads_static_risk.geojson"
REQUESTED_START = (113.9000, 22.5200)
REQUESTED_END = (114.0500, 22.5900)
RISK_ALPHA = 10.0
PIXEL_SIZE = 0.0002777777777777778


def point_key(coord):
    return round(float(coord[0]), 7), round(float(coord[1]), 7)


def haversine_m(a, b) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(h))


def nearest_node(nodes, requested):
    return min(nodes, key=lambda p: haversine_m(p, requested))


def sample_raster_along_line(coords, arr, geotransform):
    inv = gdal.InvGeoTransform(geotransform)
    if inv is None:
        raise RuntimeError("Cannot invert raster transform")
    samples = []
    height, width = arr.shape

    def add_sample(x, y):
        px = int(inv[0] + inv[1] * x + inv[2] * y)
        py = int(inv[3] + inv[4] * x + inv[5] * y)
        if 0 <= px < width and 0 <= py < height:
            val = float(arr[py, px])
            if np.isfinite(val):
                samples.append(val)

    for a, b in zip(coords[:-1], coords[1:]):
        x1, y1 = a
        x2, y2 = b
        dist = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(math.ceil(dist / PIXEL_SIZE)))
        for i in range(n + 1):
            t = i / n
            add_sample(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
    return samples


def add_edge(graph, u, v, distance, risk, way_id, highway, geometry):
    graph.setdefault(u, []).append(
        {
            "to": v,
            "distance": distance,
            "risk": risk,
            "way_id": way_id,
            "highway": highway,
            "geometry": geometry,
        }
    )


def build_dynamic_roads(dynamic_raster: Path, scenario_name: str) -> Path:
    roads = json.loads(ROADS_STATIC.read_text(encoding="utf-8"))
    ds = gdal.Open(str(dynamic_raster))
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    arr[arr == nodata] = np.nan
    gt = ds.GetGeoTransform()

    out_features = []
    for feature in roads.get("features", []):
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        props = dict(feature.get("properties") or {})
        vals = sample_raster_along_line(coords, arr, gt) if geom.get("type") == "LineString" else []
        if vals:
            values = np.asarray(vals, dtype=np.float32)
            props["dynamic_risk_mean"] = round(float(np.mean(values)), 4)
            props["dynamic_risk_max"] = round(float(np.max(values)), 4)
            props["dynamic_risk_p90"] = round(float(np.percentile(values, 90)), 4)
            props["dynamic_risk_samples"] = int(values.size)
        else:
            props["dynamic_risk_mean"] = props.get("risk_mean")
            props["dynamic_risk_max"] = props.get("risk_max")
            props["dynamic_risk_p90"] = props.get("risk_p90")
            props["dynamic_risk_samples"] = 0
        props["dynamic_scenario"] = scenario_name
        out_features.append({"type": "Feature", "geometry": geom, "properties": props})
    ds = None

    output = ROUTING / f"roads_dynamic_risk_{scenario_name}.geojson"
    output.write_text(
        json.dumps({"type": "FeatureCollection", "features": out_features}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return output


def build_graph(roads_path: Path, risk_field: str):
    data = json.loads(roads_path.read_text(encoding="utf-8"))
    graph = {}
    nodes = set()
    source_segments = 0
    for feature in data.get("features", []):
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") != "LineString" or len(coords) < 2:
            continue
        props = feature.get("properties") or {}
        risk = props.get(risk_field, props.get("risk_mean", 0.8))
        try:
            risk = float(risk)
        except (TypeError, ValueError):
            risk = 0.8
        risk = max(0.0, min(1.0, risk))
        way_id = props.get("osm_id")
        highway = props.get("highway")
        oneway = str(props.get("oneway") or "").lower()
        for a, b in zip(coords[:-1], coords[1:]):
            u = point_key(a)
            v = point_key(b)
            if u == v:
                continue
            distance = haversine_m(u, v)
            nodes.add(u)
            nodes.add(v)
            source_segments += 1
            forward = [list(u), list(v)]
            backward = [list(v), list(u)]
            if oneway == "-1":
                add_edge(graph, v, u, distance, risk, way_id, highway, backward)
            elif oneway in {"yes", "true", "1"}:
                add_edge(graph, u, v, distance, risk, way_id, highway, forward)
            else:
                add_edge(graph, u, v, distance, risk, way_id, highway, forward)
                add_edge(graph, v, u, distance, risk, way_id, highway, backward)
    return graph, nodes, source_segments


def dijkstra(graph, start, goal, risk_aware: bool):
    dist = {start: 0.0}
    prev = {}
    heap = [(0.0, start)]
    while heap:
        cost, node = heapq.heappop(heap)
        if cost != dist.get(node):
            continue
        if node == goal:
            break
        for edge in graph.get(node, []):
            weight = edge["distance"] * (1 + RISK_ALPHA * edge["risk"]) if risk_aware else edge["distance"]
            new_cost = cost + weight
            if new_cost < dist.get(edge["to"], float("inf")):
                dist[edge["to"]] = new_cost
                prev[edge["to"]] = (node, edge)
                heapq.heappush(heap, (new_cost, edge["to"]))
    if goal not in dist:
        raise RuntimeError(f"No route found {start}->{goal}")
    edges = []
    node = goal
    while node != start:
        prev_node, edge = prev[node]
        edges.append((prev_node, node, edge))
        node = prev_node
    edges.reverse()
    return edges, dist[goal]


def metrics(edges):
    risk_values = [e["risk"] for _, _, e in edges]
    distance = sum(e["distance"] for _, _, e in edges)
    return {
        "distance_m": round(distance, 2),
        "distance_km": round(distance / 1000, 3),
        "mean_dynamic_risk": round(sum(risk_values) / len(risk_values), 4) if risk_values else None,
        "max_dynamic_risk": round(max(risk_values), 4) if risk_values else None,
        "edge_count": len(edges),
        "high_risk_edges_over_0_8": sum(r > 0.8 for r in risk_values),
    }


def route_feature(route_type, scenario, edges, route_metrics, start, goal):
    coords = []
    for index, (_, _, edge) in enumerate(edges):
        if index == 0:
            coords.extend(edge["geometry"])
        else:
            coords.append(edge["geometry"][-1])
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "scenario": scenario,
            "route_type": route_type,
            "start_lon": start[0],
            "start_lat": start[1],
            "end_lon": goal[0],
            "end_lat": goal[1],
            "risk_alpha": RISK_ALPHA if route_type != "shortest_route" else 0.0,
            **route_metrics,
        },
    }


def run_for_scenario(dynamic_raster: Path, scenario_name: str):
    dynamic_roads = build_dynamic_roads(dynamic_raster, scenario_name)
    graph, nodes, segments = build_graph(dynamic_roads, "dynamic_risk_mean")
    start = nearest_node(nodes, REQUESTED_START)
    goal = nearest_node(nodes, REQUESTED_END)
    shortest_edges, shortest_cost = dijkstra(graph, start, goal, False)
    dynamic_edges, dynamic_cost = dijkstra(graph, start, goal, True)
    shortest_metrics = metrics(shortest_edges)
    dynamic_metrics = metrics(dynamic_edges)
    route_fc = {
        "type": "FeatureCollection",
        "features": [
            route_feature("shortest_route", scenario_name, shortest_edges, shortest_metrics, start, goal),
            route_feature("dynamic_risk_route", scenario_name, dynamic_edges, dynamic_metrics, start, goal),
        ],
    }
    routes_path = ROUTING / f"routes_dynamic_{scenario_name}.geojson"
    routes_path.write_text(json.dumps(route_fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    result = {
        "scenario": scenario_name,
        "dynamic_raster": str(dynamic_raster),
        "dynamic_roads": str(dynamic_roads),
        "routes": str(routes_path),
        "source_segments": segments,
        "graph_nodes": len(nodes),
        "requested_start": REQUESTED_START,
        "requested_end": REQUESTED_END,
        "snapped_start": start,
        "snapped_end": goal,
        "shortest_route": {**shortest_metrics, "path_cost": round(shortest_cost, 2)},
        "dynamic_risk_route": {**dynamic_metrics, "path_cost": round(dynamic_cost, 2)},
        "route_changed": shortest_edges != dynamic_edges,
    }
    return result


def main():
    inventory = list(csv.DictReader((DYNAMIC / "dynamic_risk_inventory.csv").open(encoding="utf-8-sig")))
    # Run the wettest observed scenario and the stress scenario.
    selected = []
    observed = [r for r in inventory if r["scenario"] == "observed"]
    if observed:
        selected.append(max(observed, key=lambda r: float(r["precip_mm_h"])))
    selected.extend(r for r in inventory if r["scenario"] == "stress_30mm")

    results = []
    for row in selected:
        scenario_name = Path(row["dynamic_risk_path"]).stem.replace("dynamic_risk_", "")
        results.append(run_for_scenario(Path(row["dynamic_risk_path"]), scenario_name))

    metrics_path = ROUTING / "dynamic_routing_metrics.json"
    metrics_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    combined_features = []
    for result in results:
        combined_features.extend(json.loads(Path(result["routes"]).read_text(encoding="utf-8"))["features"])
    combined_path = ROUTING / "routes_dynamic_comparison.geojson"
    combined_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": combined_features}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(combined_path)


if __name__ == "__main__":
    gdal.UseExceptions()
    main()
