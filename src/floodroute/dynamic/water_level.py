"""深圳积涝点水位中间表；未确认的源时间不能冒充最终 timestamp。"""

import math
import pandas as pd

from .stations import SOURCE

RAW_FIELDS = ["测站编码", "时间", "水位（m）", "水位id"]
BASE_FLAGS = "timezone_unknown;time_semantics_unverified;water_level_reference_unknown;retrieved_at_unknown"


def prepare_water_interim(raw: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    """输入 raw：四个 RAW_FIELDS 字段，全部按字符串读取，单位由源表头明确为 m。

    stations：上一步的站点中间表，至少含 station_id、name、station_type。
    输出保留四个原始字段及所有记录；新增字符串编码、名称、站类、质量标记，
    可空浮点数 water_level_cm（米乘 100），以及 source_time_without_timezone。
    后者是 YYYY-MM-DDTHH:MM:SS 字符串，不含时区，明确仅供中间核验。
    retrieved_at 留空；没有 timestamp 列，不猜测观测时间和下载时间。
    排序仅按站点及解析后的源时间；原始行序可由 source_record_number 恢复。
    """
    if list(raw.columns) != RAW_FIELDS or raw.empty:
        raise ValueError("水位 CSV 为空或字段发生变化，需要重新核验")
    for field in RAW_FIELDS:
        if any(not isinstance(value, str) for value in raw[field].dropna()):
            raise ValueError(f"{field} 必须按字符串读取")
    if not {"station_id", "name", "station_type"}.issubset(stations.columns):
        raise ValueError("站点中间表缺少关联字段")
    ids = stations["station_id"]
    if (ids.isna().any() or any(not isinstance(v, str) for v in ids)
            or ids.str.strip().eq("").any() or ids.duplicated().any()):
        raise ValueError("站点表编码须为非空唯一字符串，避免关联造成行数膨胀")

    result = raw.copy(deep=True).reset_index(drop=True)
    result["source_record_number"] = range(1, len(result) + 1)
    result["station_id"] = result["测站编码"].astype("string")
    result["source_record_id"] = result["水位id"].astype("string")
    result["source"] = SOURCE
    result["original_unit"] = "m"
    result["retrieved_at"] = pd.Series(pd.NA, index=result.index, dtype="string")
    result["quality_flag"] = BASE_FLAGS

    def flag(mask, label):
        result.loc[mask.fillna(False), "quality_flag"] += ";" + label

    # 只清理用于解析的副本；原始时间中的制表符仍保留在“时间”列。
    time_text = result["时间"].astype("string").str.strip()
    expected_format = time_text.str.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}").fillna(False)
    times = pd.to_datetime(time_text.where(expected_format), format="%Y-%m-%d %H:%M:%S", errors="coerce")
    result["source_time_without_timezone"] = times.dt.strftime("%Y-%m-%dT%H:%M:%S").astype("string")
    flag(time_text.fillna("").eq(""), "source_time_missing")
    flag(times.isna() & time_text.fillna("").ne(""), "source_time_parse_error")

    value_text = result["水位（m）"].astype("string").str.strip()
    level_m = pd.to_numeric(value_text, errors="coerce").astype("Float64")
    finite = level_m.map(lambda v: False if pd.isna(v) else math.isfinite(v))
    level_cm = level_m.where(finite) * 100
    finite_cm = level_cm.map(lambda v: False if pd.isna(v) else math.isfinite(v))
    result["water_level_cm"] = level_cm.where(finite_cm)
    flag(value_text.fillna("").eq(""), "water_level_missing")
    flag(~finite & value_text.fillna("").ne(""), "water_level_invalid")
    flag(finite & ~finite_cm, "unit_conversion_overflow")
    flag(level_m.lt(0) & finite, "negative_water_level_review")

    lookup = stations.set_index("station_id")
    result["name"] = result["station_id"].map(lookup["name"])
    result["station_type"] = result["station_id"].map(lookup["station_type"])
    missing_id = result["station_id"].fillna("").str.strip().eq("")
    matched = result["station_id"].isin(ids)
    flag(missing_id, "station_id_missing")
    flag(~missing_id & ~matched, "station_not_found")
    flag(matched & result["station_type"].ne("waterlogging"), "station_type_review")
    missing_record = result["source_record_id"].fillna("").str.strip().eq("")
    flag(missing_record, "source_record_id_missing")
    flag(~missing_record & result["source_record_id"].duplicated(keep=False), "duplicate_source_record_id")

    # 无效时间不能组成可信的“同站同刻”键；这些记录已单独标记，仍全部保留。
    keyed = result.loc[~missing_id & times.notna()]
    groups = keyed.groupby(["station_id", "source_time_without_timezone"], sort=False)["water_level_cm"]
    size = groups.transform("size")
    count = groups.transform("count")
    distinct = groups.transform("nunique")
    labels = {
        "duplicate_station_timestamp_same_value": (size > 1) & (count == size) & (distinct == 1),
        "duplicate_station_timestamp_conflict": (size > 1) & (distinct > 1),
        "duplicate_station_timestamp_review": (size > 1) & (count < size) & (distinct <= 1),
    }
    for label, mask in labels.items():
        result.loc[mask.index[mask], "quality_flag"] += ";" + label
    return result.sort_values(["station_id", "source_time_without_timezone", "source_record_number"],
                              na_position="last").reset_index(drop=True)


def summarize_water(table: pd.DataFrame) -> dict:
    """输入中间表，输出质量统计；物理异常数量因测量基准未知而保持 null。"""
    counts = table["quality_flag"].str.split(";").explode().value_counts().to_dict()
    times = table["source_time_without_timezone"].dropna()
    levels = table["water_level_cm"].dropna()
    valid = table["station_id"].fillna("").str.strip().ne("") & table["source_time_without_timezone"].notna()
    groups = table.loc[valid].groupby(["station_id", "source_time_without_timezone"]).size()
    duplicates = groups[groups > 1]
    input_order = table.sort_values("source_record_number")
    missing = {f: int(table[f].fillna("").str.strip().eq("").sum()) for f in RAW_FIELDS}
    return {
        "record_count": len(table),
        "station_count": int(table.loc[table["station_id"].fillna("").str.strip().ne(""), "station_id"].nunique()),
        "missing_by_raw_field": missing,
        "missing_rate_by_raw_field": {k: v / len(table) for k, v in missing.items()},
        "source_time_start_without_timezone": None if times.empty else times.min(),
        "source_time_end_without_timezone": None if times.empty else times.max(),
        "water_level_min_cm": None if levels.empty else float(levels.min()),
        "water_level_max_cm": None if levels.empty else float(levels.max()),
        "original_unit": "m", "output_unit": "cm", "conversion_factor": 100,
        "quality_flag_counts": counts,
        "duplicate_station_time_groups": len(duplicates),
        "duplicate_station_time_extra_rows": int((duplicates - 1).sum()),
        "duplicate_station_time_affected_rows": int(duplicates.sum()),
        "invalid_source_time_count": int(table["source_time_without_timezone"].isna().sum()),
        "stations_with_unsorted_input": sum(not g["source_time_without_timezone"].is_monotonic_increasing
                                            for _, g in input_order.groupby("station_id")),
        "valid_times_sorted_within_station": all(g["source_time_without_timezone"].dropna().is_monotonic_increasing
                                                for _, g in table.groupby("station_id")),
        "physical_anomaly_count": None,
        "physical_anomaly_note": "水位基准及物理有效范围未核验；负数只标记待审查。",
        "rows_removed": 0, "standard_interface_status": "blocked",
        "blockers": BASE_FLAGS.split(";"),
    }
