from __future__ import annotations

import heapq
import json
import math
from pathlib import Path


ROOT = Path(r"D:\LaotuZhBi\laotu-data")
STATIC = ROOT / "data" / "processed" / "static_risk"
ROADS = STATIC / "roads_static_risk.geojson"
OUT = STATIC / "routing"
OUT.mkdir(parents=True, exist_ok=True)

# First MVP endpoints in the current validation bbox.
REQUESTED_START = (113.9000, 22.5200)
REQUESTED_END = (114.0500, 22.5900)
RISK_ALPHA = 10.0


def point_key(coord: list[float] | tuple[float, float]) -> tuple[float, float]:
    return round(float(coord[0]), 7), round(float(coord[1]), 7)


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(h))


def nearest_node(nodes: set[tuple[float, float]], requested: tuple[float, float]) -> tuple[float, float]:
    return min(nodes, key=lambda p: haversine_m(p, requested))


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


def build_graph() -> tuple[dict, set, int]:
    data = json.loads(ROADS.read_text(encoding="utf-8"))
    graph: dict[tuple[float, float], list[dict]] = {}
    nodes: set[tuple[float, float]] = set()
    edge_count = 0

    for feature in data.get("features", []):
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") != "LineString" or len(coords) < 2:
            continue
        props = feature.get("properties") or {}
        risk = props.get("risk_mean")
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
            edge_count += 1
            forward = [list(u), list(v)]
            backward = [list(v), list(u)]
            if oneway == "-1":
                add_edge(graph, v, u, distance, risk, way_id, highway, backward)
            elif oneway in {"yes", "true", "1"}:
                add_edge(graph, u, v, distance, risk, way_id, highway, forward)
            else:
                add_edge(graph, u, v, distance, risk, way_id, highway, forward)
                add_edge(graph, v, u, distance, risk, way_id, highway, backward)
    return graph, nodes, edge_count


def dijkstra(graph, start, goal, mode: str):
    distances = {start: 0.0}
    previous: dict[tuple[float, float], tuple[tuple[float, float], dict]] = {}
    heap = [(0.0, start)]
    while heap:
        current_cost, node = heapq.heappop(heap)
        if current_cost != distances.get(node):
            continue
        if node == goal:
            break
        for edge in graph.get(node, []):
            if mode == "shortest":
                weight = edge["distance"]
            else:
                weight = edge["distance"] * (1.0 + RISK_ALPHA * edge["risk"])
            new_cost = current_cost + weight
            if new_cost < distances.get(edge["to"], float("inf")):
                distances[edge["to"]] = new_cost
                previous[edge["to"]] = (node, edge)
                heapq.heappush(heap, (new_cost, edge["to"]))

    if goal not in distances:
        raise RuntimeError(f"No route found: {start} -> {goal}")

    path_edges = []
    node = goal
    while node != start:
        prev_node, edge = previous[node]
        path_edges.append((prev_node, node, edge))
        node = prev_node
    path_edges.reverse()
    return path_edges, distances[goal]


def route_metrics(path_edges) -> dict:
    distance = sum(e["distance"] for _, _, e in path_edges)
    risk_values = [e["risk"] for _, _, e in path_edges]
    return {
        "distance_m": round(distance, 2),
        "distance_km": round(distance / 1000.0, 3),
        "mean_risk": round(sum(risk_values) / len(risk_values), 4) if risk_values else None,
        "max_risk": round(max(risk_values), 4) if risk_values else None,
        "edge_count": len(path_edges),
        "high_risk_edges_over_0_8": sum(r > 0.8 for r in risk_values),
    }


def route_feature(route_type: str, path_edges, metrics: dict, start, goal):
    coords = []
    for index, (_, _, edge) in enumerate(path_edges):
        segment = edge["geometry"]
        if index == 0:
            coords.extend(segment)
        else:
            coords.append(segment[-1])
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "route_type": route_type,
            "start_lon": start[0],
            "start_lat": start[1],
            "end_lon": goal[0],
            "end_lat": goal[1],
            "risk_alpha": RISK_ALPHA if route_type == "risk_aware_route" else 0.0,
            **metrics,
        },
    }


def main():
    graph, nodes, source_edge_count = build_graph()
    start = nearest_node(nodes, REQUESTED_START)
    goal = nearest_node(nodes, REQUESTED_END)
    shortest_edges, shortest_cost = dijkstra(graph, start, goal, "shortest")
    risk_edges, risk_cost = dijkstra(graph, start, goal, "risk")

    shortest_metrics = route_metrics(shortest_edges)
    risk_metrics = route_metrics(risk_edges)
    output = {
        "algorithm": "Dijkstra",
        "risk_cost": "distance_m * (1 + 10.0 * risk_mean)",
        "requested_start": {"lon": REQUESTED_START[0], "lat": REQUESTED_START[1]},
        "requested_end": {"lon": REQUESTED_END[0], "lat": REQUESTED_END[1]},
        "snapped_start": {"lon": start[0], "lat": start[1]},
        "snapped_end": {"lon": goal[0], "lat": goal[1]},
        "source_road_features": source_edge_count,
        "graph_nodes": len(nodes),
        "shortest_route": {**shortest_metrics, "path_cost": round(shortest_cost, 2)},
        "risk_aware_route": {**risk_metrics, "path_cost": round(risk_cost, 2)},
        "route_changed": shortest_edges != risk_edges,
    }
    (OUT / "routing_metrics.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    routes = {
        "type": "FeatureCollection",
        "features": [
            route_feature("shortest_route", shortest_edges, shortest_metrics, start, goal),
            route_feature("risk_aware_route", risk_edges, risk_metrics, start, goal),
        ],
    }
    (OUT / "routes_comparison.geojson").write_text(
        json.dumps(routes, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    points = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": list(start)},
                "properties": {"role": "start", "requested_lon": REQUESTED_START[0], "requested_lat": REQUESTED_START[1]},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": list(goal)},
                "properties": {"role": "end", "requested_lon": REQUESTED_END[0], "requested_lat": REQUESTED_END[1]},
            },
        ],
    }
    (OUT / "route_endpoints.geojson").write_text(
        json.dumps(points, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
