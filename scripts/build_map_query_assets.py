"""Build browser-only static geometry for v1.2 map query layers.

Formal routing continues to use the complete EPSG:32650 GeoPackage. The output
assets contain simplified display geometry and identifiers only; dynamic rain
and risk values are sent separately by the persistent component.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import pandas as pd
from shapely.geometry import box, mapping

from floodroute.runtime import Runtime


FRONTEND = ROOT / "src/floodroute/ui/components/leaflet_picker/frontend"


def rounded_geometry(geometry, decimals=6):
    data = mapping(geometry)

    def rounded(value):
        if isinstance(value, (list, tuple)):
            return [rounded(item) for item in value]
        return round(value, decimals) if isinstance(value, float) else value

    data["coordinates"] = rounded(data["coordinates"])
    return data


def safe_name(value):
    text = str(value or "").strip()
    return None if not text or "�" in text else text


def build_grids(runtime):
    grids = pd.read_csv(ROOT / runtime.config["grids_path"])
    features = []
    for row in grids[["grid_id", "lon", "lat"]].itertuples(index=False):
        geometry = box(float(row.lon) - .005, float(row.lat) - .005,
                       float(row.lon) + .005, float(row.lat) + .005)
        features.append({"type": "Feature", "properties": {"grid_id": str(row.grid_id)},
                         "geometry": rounded_geometry(geometry)})
    return {"type": "FeatureCollection", "features": features}


def build_risk_roads(runtime):
    # Service alleys dominate feature count and are omitted from the display
    # layer only. They remain available to formal routing and point queries.
    roads = runtime.router.edges.loc[~runtime.router.edges.highway.eq("service")].copy()
    roads["geometry"] = roads.geometry.simplify(12, preserve_topology=True)
    signatures = roads.geometry.map(lambda geom: min(tuple(geom.coords), tuple(reversed(geom.coords))))
    roads = roads.loc[~signatures.duplicated()].copy()
    roads = roads.to_crs(4326)
    features = []
    for row in roads.itertuples():
        # Road details are queried from the formal GeoPackage after a click.
        # Keeping only the stable ID makes this one-time browser asset smaller.
        properties = {"edge_id": f"{int(row.u)}:{int(row.v)}:{int(row.key)}"}
        features.append({"type": "Feature", "properties": properties,
                         "geometry": rounded_geometry(row.geometry, decimals=5)})
    return {"type": "FeatureCollection", "features": features}, len(runtime.router.edges), len(roads)


def write_compact(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    runtime = Runtime()
    FRONTEND.mkdir(parents=True, exist_ok=True)
    grids = build_grids(runtime)
    risk_roads, source_edges, display_edges = build_risk_roads(runtime)
    grid_path = FRONTEND / "grid_cells_display.geojson"
    road_path = FRONTEND / "risk_roads_display.geojson"
    write_compact(grid_path, grids)
    write_compact(road_path, risk_roads)

    manifest_path = ROOT / "data/derived/display/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["map_query_assets"] = {
        "use": "display/query only; never routing or experiment input",
        "grid_features": len(grids["features"]),
        "grid_bytes": grid_path.stat().st_size,
        "risk_source_motor_edges": source_edges,
        "risk_display_edges": display_edges,
        "risk_display_bytes": road_path.stat().st_size,
        "risk_omitted_for_display": "service class and visually duplicate opposite directions",
        "risk_simplification_m": 12,
        "coordinate_decimals": 5,
        "static_sha256": hashlib.sha256((ROOT / runtime.config["static_path"]).read_bytes()).hexdigest(),
        "grid_sha256": hashlib.sha256((ROOT / runtime.config["grids_path"]).read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["map_query_assets"], ensure_ascii=False, indent=2))
