"""原样归档两份深圳格点 CSV，检查关联与样本覆盖；不生成最终接口。

输入为官方实况格点数据表和格点信息表，所有字段按字符串读取。
输出为不可覆盖的原件副本、归档回执和 JSON 检查报告。
源时间不添加时区，格网角点不转换 CRS，也不冒充测站坐标。
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TIMES = ["预报时间", "发布时间", "入库时间"]
RAIN = {f"{hours}小时累计降雨量（毫米）": hours * 60 for hours in [1, 2, 3, 6, 24]}
BOUNDS = ["格网左下角经度（度）", "格网左下角纬度（度）", "格网右上角经度（度）", "格网右上角纬度（度）"]


def inspect_tables(data, grids):
    """输入两个字符串 DataFrame；返回统计 dict，不修改输入或删除异常行。

    检查粒度：一条源记录，以及“格网ID+源预报时间”候选键。
    此候选键用于发现重复，尚不表示预报时间已确认是观测时间。
    """
    required = set(TIMES + list(RAIN) + ["格网ID", "记录编号", "预报时效（小时）", "预报级别", "Tracer1小时累计降雨量预报"])
    if not required.issubset(data.columns) or not set(BOUNDS + ["格网ID（唯一）"]).issubset(grids.columns):
        raise ValueError("源字段变化：请先检查列名")
    if data.empty or grids.empty:
        raise ValueError("空数据不能完成验收")
    for frame in [data, grids]:
        for col in frame:
            if not frame[col].map(lambda value: isinstance(value, str)).all():
                raise ValueError("所有原始字段必须按字符串读取")
    missing = lambda frame: {col: int(frame[col].str.strip().eq("").sum()) for col in frame}
    parsed = {col: pd.to_datetime(data[col].str.strip(), format="%Y-%m-%d %H:%M:%S", errors="coerce") for col in TIMES}
    times = {col: {"min_without_timezone": None if values.dropna().empty else str(values.min()),
                   "max_without_timezone": None if values.dropna().empty else str(values.max()),
                   "unique_count": int(values.nunique()), "invalid_or_missing": int(values.isna().sum())}
             for col, values in parsed.items()}
    rainfall = {}
    for col in list(RAIN) + ["Tracer1小时累计降雨量预报"]:
        values = pd.to_numeric(data[col], errors="coerce")
        finite = values.notna() & np.isfinite(values)
        usable = values[finite]
        rainfall[col] = {"interval_min_from_column_label": RAIN.get(col),
                         "finite_count": int(finite.sum()), "missing_or_nonfinite_count": int((~finite).sum()),
                         "negative_count": int(usable.lt(0).sum()), "zero_count": int(usable.eq(0).sum()),
                         "positive_count": int(usable.gt(0).sum()),
                         "min": None if usable.empty else float(usable.min()),
                         "max": None if usable.empty else float(usable.max())}
    ids, grid_ids = data["格网ID"].str.strip(), grids["格网ID（唯一）"].str.strip()
    known_ids = grid_ids[grid_ids.ne("")]
    matched = ids.ne("") & ids.isin(known_ids)
    geometry = grids[BOUNDS].apply(pd.to_numeric, errors="coerce")
    left, bottom, right, top = [geometry[col] for col in BOUNDS]
    finite_bounds = pd.Series(np.isfinite(geometry.to_numpy(dtype=float, na_value=np.nan)).all(axis=1), index=grids.index)
    bounds_valid = (finite_bounds & left.between(-180, 180) & right.between(-180, 180)
                    & bottom.between(-90, 90) & top.between(-90, 90) & left.lt(right) & bottom.lt(top)).fillna(False)
    # 不做 many-to-many merge：先审查名录唯一性；以成员匹配计数检验外键。
    key = pd.DataFrame({"grid_id": ids, "source_time": parsed["预报时间"]})
    valid_key = ids.ne("") & key["source_time"].notna()
    groups = key.loc[valid_key].groupby(["grid_id", "source_time"]).size()
    duplicate_groups = groups[groups.gt(1)]
    per_time = key.loc[valid_key].groupby("source_time").agg(rows=("grid_id", "size"), grid_count=("grid_id", "nunique"))
    coverage = [{"source_time_without_timezone": str(t), "rows": int(row['rows']), "unique_grid_count": int(row['grid_count'])}
                for t, row in per_time.iterrows()]
    unique_times = pd.Series(sorted(parsed["预报时间"].dropna().unique()), dtype="datetime64[ns]")
    gaps = unique_times.diff().dt.total_seconds().div(60).dropna()
    return {
        "data_rows": len(data), "data_columns": list(data.columns), "grid_rows": len(grids), "grid_columns": list(grids.columns),
        "data_missing_by_column": missing(data), "grid_missing_by_column": missing(grids),
        "grid_unique_ids": int(known_ids.nunique()), "grid_duplicate_id_rows": int(grid_ids.duplicated(keep=False).sum()),
        "data_unique_grid_ids": int(ids[ids.ne("")].nunique()), "matched_data_rows": int(matched.sum()),
        "unmatched_data_rows": int((~matched).sum()), "unmatched_grid_id_examples": ids[~matched].unique().tolist()[:20],
        "safe_many_to_one_join": bool(grid_ids.ne("").all() and not grid_ids.duplicated().any()),
        "invalid_grid_bounds_count": int((~bounds_valid).sum()),
        "raw_coordinate_envelope": {"west": float(left.min()), "east": float(right.max()), "south": float(bottom.min()), "north": float(top.max())} if bounds_valid.all() else None,
        "coordinate_crs": "coordinate_crs_unknown", "spatial_type": "interpolated_observation_grid",
        "source_times": times, "forecast_lead_counts": data["预报时效（小时）"].value_counts().to_dict(),
        "forecast_level_counts": data["预报级别"].value_counts().to_dict(),
        "issue_and_forecast_time_equal_rows": int((parsed["发布时间"].notna() & parsed["发布时间"].eq(parsed["预报时间"])).sum()),
        "adjacent_source_time_gap_minutes_counts": {str(k): int(v) for k, v in gaps.value_counts().items()},
        "per_source_time_coverage": coverage,
        "time_slices_with_fewer_grids_than_registry": sum(row["unique_grid_count"] < known_ids.nunique() for row in coverage),
        "duplicate_grid_source_time_groups": len(duplicate_groups), "duplicate_grid_source_time_affected_rows": int(duplicate_groups.sum()),
        "duplicate_record_id_rows": int(data["记录编号"].duplicated(keep=False).sum()),
        "rainfall_columns": rainfall, "raw_rows_removed": 0,
        "standard_interface_status": "blocked", "processing_stage": "sample_inspected",
        "blockers": ["coordinate_crs_unknown", "timezone_unknown", "observation_time_field_unconfirmed", "retrieved_at_unknown"],
        "cautions": ["grid_is_not_station", "sample_is_not_complete_requested_history", "rainfall_window_anchor_unconfirmed",
                     "tracer_forecast_is_not_observed_rainfall", "zero_rainfall_sample_does_not_validate_heavy_rain_use"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--grids", type=Path, required=True)
    args = parser.parse_args()
    inputs = {"data": args.data.resolve(), "grids": args.grids.resolve()}
    originals = {key: path.read_bytes() for key, path in inputs.items()}
    frames = {key: pd.read_csv(io.BytesIO(value), dtype="string", keep_default_na=False, encoding="utf-8-sig") for key, value in originals.items()}
    report = inspect_tables(frames["data"], frames["grids"])
    now = datetime.now(timezone(timedelta(hours=8)))
    run = "shenzhen_grid_" + now.strftime("%Y%m%dT%H%M%S%f%z")
    raw_folder = ROOT / "data/raw/dynamic/rainfall" / run
    raw_folder.mkdir(parents=True, exist_ok=False)
    evidence = {}
    for key, original in originals.items():
        target = raw_folder / inputs[key].name
        with target.open("xb") as stream:
            stream.write(original)
        digest = hashlib.sha256(original).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest or inputs[key].read_bytes() != original:
            raise RuntimeError("原件/归档哈希不一致")
        evidence[key] = {"provided_path": str(inputs[key]), "raw_path": target.relative_to(ROOT).as_posix(),
                         "bytes": len(original), "sha256": digest}
    receipt = {"archived_at": now.isoformat(), "retrieved_at": None,
               "notes": "用户手动下载后提供；archived_at仅为本地归档时间，不冒充网站获取时间。", "files": evidence}
    with (raw_folder / "archive_receipt.json").open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
    report.update(checked_at=now.isoformat(), files=evidence,
                  receipt_path=(raw_folder / "archive_receipt.json").relative_to(ROOT).as_posix(),
                  official_urls={"data": "https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_00903509",
                                 "grids": "https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_00903510"})
    output_folder = ROOT / "outputs/dynamic" / run
    output_folder.mkdir(parents=True, exist_ok=False)
    output = output_folder / "quality_report.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"report_path": str(output), "raw_folder": str(raw_folder),
                      "data_rows": report["data_rows"], "grid_rows": report["grid_rows"],
                      "matched_data_rows": report["matched_data_rows"], "status": report["standard_interface_status"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
