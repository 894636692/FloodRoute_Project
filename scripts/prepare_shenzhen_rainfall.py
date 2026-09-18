"""生成独立的真实格网降雨候选接口，不覆盖现有 B fixture。"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from floodroute.dynamic.shenzhen_rainfall import normalize_shenzhen_rainfall

RAW = ROOT / "data/raw/dynamic/rainfall/shenzhen_grid_20260918T142832315164+0800"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/derived/dynamic/shenzhen_grid")
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    if not destination.is_relative_to((ROOT / "data/derived/dynamic").resolve()) or destination.exists():
        parser.error("输出目录须为 data/derived/dynamic 内尚不存在的新目录，避免覆盖")
    paths = {"data": RAW / "深圳范围自动站实况格点数据表_2920000903509.csv",
             "grids": RAW / "深圳范围自动站实况格点信息表_2920000903510.csv",
             "metadata": ROOT / "docs/shenzhen_rainfall_metadata.json"}
    contents = {key: path.read_bytes() for key, path in paths.items()}
    receipt = json.loads((RAW / "archive_receipt.json").read_text(encoding="utf-8"))
    for key in ["data", "grids"]:
        if hashlib.sha256(contents[key]).hexdigest() != receipt["files"][key]["sha256"]:
            raise ValueError("原始数据哈希与归档回执不符")
    frames = {key: pd.read_csv(io.BytesIO(contents[key]), dtype="string", keep_default_na=False) for key in ["data", "grids"]}
    metadata = json.loads(contents["metadata"])
    interim, hourly, cells = normalize_shenzhen_rainfall(frames["data"], frames["grids"], metadata)
    now = datetime.now(timezone(timedelta(hours=8)))
    folder = ROOT / "data/interim/dynamic" / ("shenzhen_rainfall_" + now.strftime("%Y%m%dT%H%M%S%f%z"))
    for key, path in paths.items():
        if contents[key] != path.read_bytes():
            raise RuntimeError("处理期间输入发生变化")
    folder.mkdir(parents=True, exist_ok=False)
    destination.mkdir(parents=True, exist_ok=False)
    interim.to_csv(folder / "rainfall_interim.csv", index=False, encoding="utf-8-sig", mode="x")
    hourly.to_csv(destination / "rainfall.csv", index=False, encoding="utf-8-sig", mode="x")
    cells.to_csv(destination / "grid_cells.csv", index=False, encoding="utf-8-sig", mode="x")
    # 读回原字段，确认关联、排序和标准化没有修改或删除原记录。
    readback = pd.read_csv(folder / "rainfall_interim.csv", dtype="string", keep_default_na=False)
    recovered = readback.assign(_order=readback["source_record_number"].astype(int)).sort_values("_order")[frames["data"].columns].reset_index(drop=True)
    pd.testing.assert_frame_equal(recovered, frames["data"])
    final = pd.read_csv(destination / "rainfall.csv", dtype={"station_id": "string"})
    assert len(final) == len(frames["data"])
    assert final["interval_min"].eq(60).all()
    report = {"processed_at": now.isoformat(), "record_count": len(hourly), "grid_count": len(cells),
              "timestamp_start": hourly["timestamp"].dropna().min(), "timestamp_end": hourly["timestamp"].dropna().max(),
              "rain_min_mm": float(hourly["rain_mm"].min()), "rain_max_mm": float(hourly["rain_mm"].max()),
              "rain_missing_count": int(hourly["rain_mm"].isna().sum()), "rain_negative_count": int(hourly["rain_mm"].lt(0).sum()),
              "missing_coordinate_rows": int(hourly[["lon", "lat"]].isna().any(axis=1).sum()),
              "invalid_time_rows": int(hourly["timestamp"].isna().sum()),
              "duplicate_grid_timestamp_rows": int(hourly.duplicated(["grid_id", "timestamp"], keep=False).sum()),
              "quality_flag_counts": hourly["quality_flag"].str.split(";").explode().value_counts().to_dict(),
              "raw_fields_readback_verified": True, "raw_rows_removed": 0,
              "time_definition_provenance": "user_confirmation", "coordinate_crs": "EPSG:4326",
              "coordinate_role": "grid_center_not_station", "standard_interface_status": "candidate_requires_integration_review",
              "blockers": ["retrieved_at_unknown", "B_grid_mapping_and_quality_flag_handling_not_validated"],
              "interim_path": (folder / "rainfall_interim.csv").relative_to(ROOT).as_posix(),
              "output_path": (destination / "rainfall.csv").relative_to(ROOT).as_posix(),
              "grid_path": (destination / "grid_cells.csv").relative_to(ROOT).as_posix(),
              "inputs": {key: {"path": paths[key].relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(value).hexdigest()} for key, value in contents.items()}}
    with (destination / "quality_report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
