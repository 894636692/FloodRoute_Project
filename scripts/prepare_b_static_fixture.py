"""Prepare a temporary A -> B static feature file from existing repo data.

This script does not download GIS data. It converts the previously generated
OSM edges plus sampled node attributes into the B input contract:
data/derived/static/road_static_features.gpkg

When A's official edge-level road_static_features.gpkg is ready, replace this
fixture with that file and keep B code unchanged.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EDGES_PATH = ROOT / "data" / "processed" / "shenzhen_core" / "osm_edges_utm.geojson"
NODES_PATH = ROOT / "results" / "real_shenzhen" / "real_nodes_sampled.csv"
OUT_PATH = ROOT / "data" / "derived" / "static" / "road_static_features.gpkg"


def highway_to_text(value) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value) if value is not None else ""


def main() -> None:
    edges = gpd.read_file(EDGES_PATH)
    nodes = pd.read_csv(NODES_PATH).set_index("osmid")
    rows = []
    for row in edges.itertuples():
        u = int(row.u)
        v = int(row.v)
        if u not in nodes.index or v not in nodes.index:
            continue
        first = nodes.loc[u]
        second = nodes.loc[v]
        elev_mean = float((first["elevation"] + second["elevation"]) / 2)
        elev_min = float(min(first["elevation"], second["elevation"]))
        low_elev = float((first["low_elevation"] + second["low_elevation"]) / 2)
        flatness = float((first["slope_risk"] + second["slope_risk"]) / 2)
        builtup = float(((first["worldcover"] == 50) + (second["worldcover"] == 50)) / 2)
        water = float(((first["worldcover"] == 80) + (second["worldcover"] == 80)) / 2)
        vegetation = float(
            ((first["worldcover"] in {10, 20, 30, 40}) + (second["worldcover"] in {10, 20, 30, 40})) / 2
        )
        rows.append(
            {
                "u": u,
                "v": v,
                "key": int(row.key),
                "length_m": float(getattr(row, "length", row.geometry.length)),
                "highway": highway_to_text(getattr(row, "highway", "")),
                "oneway": str(getattr(row, "oneway", "")),
                "elev_mean_m": elev_mean,
                "elev_min_m": elev_min,
                "low_elev_norm": low_elev,
                "slope_mean_deg": float((1.0 - flatness) * 12.0),
                "slope_p90_deg": float((1.0 - flatness) * 16.0),
                "flatness_risk": flatness,
                "builtup_frac": builtup,
                "vegetation_frac": vegetation,
                "water_frac": water,
                "source_version": "fixture-from-9837168-real-shenzhen",
                "geometry": row.geometry,
            }
        )

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=edges.crs)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(OUT_PATH, driver="GPKG")
    print(f"wrote {len(gdf)} edges -> {OUT_PATH}")


if __name__ == "__main__":
    main()

