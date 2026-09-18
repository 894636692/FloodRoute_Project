"""Inspect downloaded water-level CSV and its station registry; never edit raw data.

Run with WATER_CSV STATIONS_CSV and optionally --output outputs/...json.
Only inspection results are saved. The existing derived water_level.csv is untouched.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WATER_FIELDS = ["测站编码", "时间", "水位（m）", "水位id"]
STATION_FIELDS = ["测站编码", "测站名称", "站类"]


def file_hashes(folder):
    """Return SHA-256 for each original export file, without changing any file."""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower()
            in {".csv", ".json", ".xml", ".rdf", ".xlsx"}}


def inspect_download(water_path, stations_path):
    """Return statistics and review flags as a dict, not a standardized DataFrame.

    Input water DataFrame fields: 测站编码, 时间, 水位（m）, 水位id, all strings.
    Input stations fields: 测站编码, 测站名称, 站类, all strings.
    A separate in-memory DataFrame strips time whitespace for parsing and converts
    metre values to numbers for checking. Time stays timezone-naive; no +08:00 is
    assigned. No rows are removed and no water-level-to-depth assumption is made.
    """
    hashes_before = file_hashes(water_path.parent)
    water = pd.read_csv(water_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    stations = pd.read_csv(stations_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if list(water.columns) != WATER_FIELDS or list(stations.columns) != STATION_FIELDS:
        raise ValueError("Source schema changed; inspect headers before proceeding.")
    if water.empty or stations["测站编码"].duplicated().any():
        raise ValueError("Water data is empty or the station registry has duplicate IDs.")
    check = pd.DataFrame({
        "station_id": water["测站编码"], "source_record_id": water["水位id"],
        "source_time_stripped": water["时间"].str.strip(),
        "level_m": pd.to_numeric(water["水位（m）"], errors="coerce"),
    })
    times = pd.to_datetime(check["source_time_stripped"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    groups = check.groupby(["station_id", "source_time_stripped"], sort=False).agg(
        records=("source_record_id", "size"), distinct_values=("level_m", "nunique"))
    duplicates = groups[groups["records"] > 1]
    review_groups = []
    for (station_id, source_time), group in check.groupby(["station_id", "source_time_stripped"], sort=False):
        if len(group) > 1:
            same_value = group["level_m"].notna().all() and group["level_m"].nunique() == 1
            review_groups.append({
                "station_id": station_id, "source_time_stripped": source_time,
                "source_record_ids": group["source_record_id"].tolist(),
                "quality_flag": "duplicate_station_timestamp_same_value" if same_value
                                else "duplicate_station_timestamp_review",
            })
    station_types = stations.set_index("测站编码")["站类"].to_dict()
    water_ids = set(check["station_id"])
    unknown_ids = sorted(water_ids - set(station_types))
    metadata = {}
    rdf_files = list(water_path.parent.glob("*.rdf"))
    if len(rdf_files) == 1:
        for description in ET.parse(rdf_files[0]).getroot():
            fields = {child.tag.rsplit("}", 1)[-1]: child.text for child in description}
            if "resourceid" in fields:
                metadata = fields
    json_files = list(water_path.parent.glob("*.json"))
    json_check = {"checked": False}
    if len(json_files) == 1:
        try:
            json.loads(json_files[0].read_text(encoding="utf-8-sig"))
            json_check = {"checked": True, "strict_valid": True}
        except json.JSONDecodeError as error:
            json_check = {"checked": True, "strict_valid": False, "error": str(error)}
    missing = {field: int(water[field].str.strip().eq("").sum()) for field in WATER_FIELDS}
    report = {
        "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "raw_path": str(water_path.resolve()), "source_sha256": hashes_before,
        "source_fields": WATER_FIELDS, "source_metadata": metadata,
        "record_count": len(water), "station_count": len(water_ids),
        "missing_by_field": missing, "missing_rate_by_field": {k: v / len(water) for k, v in missing.items()},
        "source_time_start_without_timezone": None if times.isna().all() else str(times.min()),
        "source_time_end_without_timezone": None if times.isna().all() else str(times.max()),
        "source_timezone": "unknown", "source_time_semantics": "采集时间；是否为实际观测时刻尚未确认",
        "invalid_time_count": int(times.isna().sum()),
        "time_rows_with_leading_tab": int(water["时间"].str.startswith("\t").sum()),
        "global_time_sorted": bool(times.is_monotonic_increasing),
        "stations_with_unsorted_input": sum(not times.loc[index].is_monotonic_increasing
                                            for index in water.groupby("测站编码").groups.values()),
        "raw_date_counts": times.dt.strftime("%Y-%m-%d").value_counts().sort_index().to_dict(),
        "original_unit": "m", "water_level_min_m": float(check["level_m"].min()),
        "water_level_max_m": float(check["level_m"].max()),
        "non_numeric_value_count": int(check["level_m"].isna().sum()),
        "negative_value_count": int(check["level_m"].lt(0).sum()),
        "zero_value_count": int(check["level_m"].eq(0).sum()),
        "physical_anomaly_count": None, "physical_anomaly_note": "Reference level and valid physical range are unverified.",
        "matched_station_count": len(water_ids & set(station_types)), "unmatched_station_ids": unknown_ids,
        "matched_station_types": pd.Series([station_types[sid] for sid in water_ids if sid in station_types]).value_counts().to_dict(),
        "duplicate_station_time_groups": len(duplicates),
        "duplicate_station_time_extra_rows": int((duplicates["records"] - 1).sum()),
        "duplicate_station_time_affected_rows": int(duplicates["records"].sum()),
        "duplicate_station_time_conflicting_value_groups": int(duplicates["distinct_values"].gt(1).sum()),
        "exact_duplicate_extra_rows": int(water.duplicated().sum()),
        "duplicate_source_record_id_extra_rows": int(water["水位id"].duplicated().sum()),
        "all_record_quality_flags": ["timezone_unknown", "time_semantics_unverified", "water_level_reference_unknown"],
        "duplicate_review_groups": review_groups, "source_json_check": json_check,
        "history_complete": None, "history_note": "This file has 100000 rows; export limit and earlier history are unverified.",
        "retrieved_at_note": "Exact manual download time unverified; checked_at is inspection time only.",
        "standard_interface_status": "blocked", "rows_removed": 0,
    }
    if file_hashes(water_path.parent) != hashes_before:
        raise RuntimeError("Raw export files changed during inspection.")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("water_csv", type=Path)
    parser.add_argument("stations_csv", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inspect_download(args.water_csv, args.stations_csv)
    if args.output:
        if not args.output.resolve().is_relative_to(PROJECT_ROOT / "outputs"):
            parser.error("The report must be saved inside the project's outputs/ directory.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    for key in ["record_count", "station_count", "matched_station_count", "missing_by_field",
                "source_time_start_without_timezone", "source_time_end_without_timezone",
                "water_level_min_m", "water_level_max_m", "duplicate_station_time_groups",
                "duplicate_station_time_extra_rows", "duplicate_station_time_conflicting_value_groups"]:
        print(f"{key}: {report[key]}")
    print("Rows removed: 0. Standard water-level interface: BLOCKED; review source semantics.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
