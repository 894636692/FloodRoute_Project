"""Exercise B's real GraphML/GPKG contract and a keyed directed shortest route."""
import json
import math
from pathlib import Path
import ab_runtime
import networkx as nx
from osgeo import ogr, osr
from floodroute.gis.static_features import load_feature_graph, spatial_ref, read_area, write_json

ROOT = ab_runtime.ROOT
OUT = ROOT / "data/derived/static"


def main():
    ogr.UseExceptions()
    features = load_feature_graph(OUT / "road_static_features.gpkg")
    source = nx.read_graphml(OUT / "roads.graphml", node_type=int, edge_key_type=int, force_multigraph=True)
    assert isinstance(features, nx.MultiDiGraph) and isinstance(source, nx.MultiDiGraph)
    assert set(features.edges(keys=True)) == set(source.edges(keys=True))
    raw = json.loads((ROOT / "data/raw/osm/shenzhen_center_roads_overpass_2026-09-17.json").read_text(encoding="utf-8"))
    ways = {e["id"]: e for e in raw["elements"] if e["type"] == "way"}
    checked = 0
    for u, v, key, data in source.edges(keys=True, data=True):
        nodes = ways[data["osm_way_id"]]["nodes"]
        start_node = nodes[data["segment_index"]]
        assert (v if data["reversed"] else u) == start_node
        assert features[u][v][key]["geometry_wkt"] == data["geometry_wkt"]
        checked += 1
    # Vehicle baseline deliberately excludes footways, private access and construction.
    allowed = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
               "secondary", "secondary_link", "tertiary", "tertiary_link", "residential",
               "unclassified", "living_street", "service"}
    vehicle = nx.MultiDiGraph()
    for u, v, key, data in features.edges(keys=True, data=True):
        tags = json.loads(data["osm_tags_json"])
        access = next((tags[t] for t in ("motorcar", "motor_vehicle", "vehicle", "access") if t in tags), "yes")
        if data["highway"] in allowed and access not in {"no", "private"} and not any(":" in t and t.endswith("conditional") for t in tags):
            vehicle.add_edge(u, v, key=key, **data)
    component = max(nx.strongly_connected_components(vehicle), key=len)
    vehicle = vehicle.subgraph(component).copy()
    request = json.loads((ROOT / "config/ab_baseline_request.json").read_text(encoding="utf-8"))
    forward = osr.CoordinateTransformation(spatial_ref("EPSG:4326"), spatial_ref("EPSG:32650"))
    backward = osr.CoordinateTransformation(spatial_ref("EPSG:32650"), spatial_ref("EPSG:4326"))
    requested = [forward.TransformPoint(*request[k])[:2] for k in ("start", "goal")]
    area, _ = read_area(ROOT / "study_area.geojson")
    for xy in requested:
        p = ogr.Geometry(ogr.wkbPoint)
        p.AddPoint_2D(*xy)
        assert area.Intersects(p), "Requested endpoint outside study_area"
    def distance(node, xy):
        return math.dist((features.nodes[node]["x"], features.nodes[node]["y"]), xy)
    start, goal = [min(vehicle.nodes, key=lambda n: distance(n, xy)) for xy in requested]
    snapped = [distance(start, requested[0]), distance(goal, requested[1])]
    assert max(snapped) <= request["max_snap_distance_m"], "Endpoint too far from vehicle network"
    nodes = nx.shortest_path(vehicle, start, goal, weight="length_m")
    edge_ids, coordinates, length = [], [], 0.0
    for u, v in zip(nodes, nodes[1:]):
        key = min(vehicle[u][v], key=lambda k: (vehicle[u][v][k]["length_m"], k))
        data = vehicle[u][v][key]
        edge_ids.append([u, v, key])
        geom = ogr.CreateGeometryFromWkt(data["geometry_wkt"])
        geom.Transform(backward)
        coords = [list(p[:2]) for p in geom.GetPoints()]
        coordinates.extend(coords if not coordinates else coords[1:])
        length += data["length_m"]
    assert abs(length - nx.shortest_path_length(vehicle, start, goal, weight="length_m")) < 0.001
    result = dict(mode="shortest", schema_version="1.0.0", distance_m=length, edge_ids=edge_ids,
        snap_distances_m=snapped, requested=request, route_edge_count=len(edge_ids),
        limitation="Connectivity baseline only; no flood safety or turn-restriction validation")
    write_json(OUT / "b_baseline_route.json", result)
    write_json(OUT / "b_baseline_route.geojson", {"type": "FeatureCollection", "features": [{"type": "Feature",
        "properties": {"mode": "shortest", "distance_m": length, "edge_count": len(edge_ids)},
        "geometry": {"type": "LineString", "coordinates": coordinates}}]})
    verification = dict(passed=True, graphml_gpkg_edge_ids_equal=True, provenance_edges_checked=checked,
        actual_multidigraph=True, parallel_pairs=sum(len(keys) > 1 for u in source for keys in source[u].values()),
        vehicle_component_nodes=len(component), route_edge_count=len(edge_ids), route_distance_m=length,
        snap_distances_m=snapped, official_networkx_version=nx.__version__)
    write_json(OUT / "b_acceptance_report.json", verification)
    print(json.dumps(verification))


if __name__ == "__main__":
    main()
