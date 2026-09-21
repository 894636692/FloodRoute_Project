"""Offline-only matching of reported historical impacts to formal road IDs."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import geopandas as gpd
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EVENT_DIR = ROOT / "data/historical/shenzhen_2023_0907"
THRESHOLDS_M = (50.0, 100.0, 200.0)
MAIN_THRESHOLD_M = 100.0


def build_labels(reports: pd.DataFrame, roads: gpd.GeoDataFrame) -> tuple[pd.DataFrame, dict]:
    """Match auditable point locations to their single nearest formal edge.

    Rows without coordinates are retained in ``impact_reports.csv`` but are not
    silently geocoded here.  The output preserves exact directed ``(u,v,key)``.
    """
    required = {
        "report_id", "reported_time_start", "reported_time_end", "lon", "lat",
        "geocode_method", "match_confidence",
    }
    missing = required.difference(reports.columns)
    if missing:
        raise ValueError(f"Missing report columns: {sorted(missing)}")
    candidates = reports.dropna(subset=["lon", "lat"]).copy()
    candidates = candidates[candidates.match_confidence.isin(["high", "medium"])]
    points = gpd.GeoDataFrame(
        candidates,
        geometry=gpd.points_from_xy(candidates.lon, candidates.lat),
        crs="EPSG:4326",
    ).to_crs(roads.crs)
    edge_cols = ["u", "v", "key", "osm_way_id", "highway", "length_m", "static_risk"]
    nearest = gpd.sjoin_nearest(points, roads[edge_cols + ["geometry"]], how="left", distance_col="match_distance_m")
    nearest = nearest.sort_values(["report_id", "match_distance_m", "u", "v", "key"]).drop_duplicates("report_id")
    for threshold in THRESHOLDS_M:
        nearest[f"within_{int(threshold)}m"] = nearest.match_distance_m.le(threshold)
    nearest["eligible_main"] = nearest.match_distance_m.le(MAIN_THRESHOLD_M) & nearest.match_confidence.eq("high")
    nearest["match_method"] = "nearest_formal_edge_from_audited_point"
    nearest["event_time_start"] = nearest.reported_time_start
    nearest["event_time_end"] = nearest.reported_time_end
    out_cols = [
        "report_id", "u", "v", "key", "osm_way_id", "highway", "length_m", "static_risk",
        "match_distance_m", "match_method", "match_confidence", "event_time_start", "event_time_end",
        "within_50m", "within_100m", "within_200m", "eligible_main",
    ]
    output = nearest[out_cols].copy()
    for col in ["u", "v", "key", "osm_way_id"]:
        output[col] = output[col].astype("int64")
    summary = {
        "input_reports": int(len(reports)),
        "reports_with_coordinates": int(reports[["lon", "lat"]].notna().all(axis=1).sum()),
        "auditable_candidates": int(len(candidates)),
        "matched_rows": int(len(output)),
        "main_threshold_m": MAIN_THRESHOLD_M,
        "main_eligible_rows": int(output.eligible_main.sum()),
        "threshold_sensitivity": {
            str(int(t)): int(output[f"within_{int(t)}m"].sum()) for t in THRESHOLDS_M
        },
        "unlocated_or_excluded_report_ids": sorted(set(reports.report_id) - set(output.report_id)),
    }
    return output, summary


def main() -> None:
    reports = pd.read_csv(EVENT_DIR / "impact_reports.csv")
    roads = gpd.read_file(ROOT / "data/derived/static/road_static_features.gpkg", layer="road_static_features")
    # Static risk is fixed by v1.2.0 and is used only for transparent background matching.
    from floodroute.risk.static import static_components
    config = json.loads((ROOT / "config/selected_v1_1.json").read_text(encoding="utf-8"))
    roads["static_risk"] = static_components(roads, config)[0]
    output, summary = build_labels(reports, roads)
    output.to_parquet(EVENT_DIR / "impact_roads.parquet", index=False)
    (EVENT_DIR / "impact_label_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
