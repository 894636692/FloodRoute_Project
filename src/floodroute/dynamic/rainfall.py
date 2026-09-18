"""NOAA ISD 历史降水候选的中间解析，不代表深圳当前实时降雨接口。"""

from datetime import datetime, timezone
import math
import re

import pandas as pd

SOURCE = "NOAA NCEI Global Hourly (ISD)"
REQUIRED = {"STATION", "DATE", "NAME", "LATITUDE", "LONGITUDE"}
CONDITIONS = {
    "1": "measurement_inaccurate", "2": "trace_precipitation",
    "3": "accumulation_begin_review", "4": "accumulation_end_review",
    "5": "deleted_period_begin", "6": "deleted_period_end",
    "7": "missing_period_begin", "8": "missing_period_end",
    "9": "condition_code_missing", "E": "estimated_precipitation",
    "I": "incomplete_missing_reports", "J": "incomplete_erroneous_reports",
}
QUALITY = {
    "0": "source_qc_gross_limits", "1": "source_qc_passed",
    "2": "source_qc_suspect", "3": "source_qc_erroneous",
    "4": "source_qc_gross_limits", "5": "source_qc_passed",
    "6": "source_qc_suspect", "7": "source_qc_erroneous",
    "9": "source_qc_gross_limits_if_present", "A": "source_qc_suspect_accepted",
    "I": "source_qc_inserted", "M": "source_qc_manual_change",
    "P": "source_qc_replaced", "R": "source_qc_computed", "U": "source_qc_edited",
}


def parse_precipitation_group(value: str) -> dict:
    """解码 AA1–AA4：小时数,十分之一毫米数,条件码,质量码。

    返回 rain_mm(float/None)、interval_min(int/None)、原代码及 flags(list)。
    99 小时、9999 深度是缺失哨兵，不是 99 小时或 999.9 毫米降雨。
    特殊条件码保留，绝不自动补雨、重分配累计量或把微量降水改为精确零。
    """
    result = {"rain_mm": None, "interval_min": None, "source_condition_code": "",
              "source_quality_code": "", "flags": []}
    if not value.strip():
        result["flags"] = ["precipitation_group_missing"]
        return result
    match = re.fullmatch(r"(\d{2}),(\d{4}),([0-9A-Z]),([0-9A-Z])", value.strip())
    if not match:
        result["flags"] = ["precipitation_group_parse_error"]
        return result
    hours, depth, condition, quality = match.groups()
    result["source_condition_code"] = condition
    result["source_quality_code"] = quality
    if hours == "99":
        result["flags"].append("interval_unknown")
    elif hours == "00":
        result["flags"].append("zero_interval_review")
    else:
        result["interval_min"] = int(hours) * 60
    if depth == "9999":
        result["flags"].append("rain_missing")
    else:
        result["rain_mm"] = int(depth) / 10.0
    result["flags"].append(CONDITIONS.get(condition, "condition_code_unknown"))
    result["flags"].append(QUALITY.get(quality, "quality_code_unknown"))
    if condition == "3" and result["rain_mm"] is not None:
        result["flags"].append("accumulation_begin_with_value_review")
    return result


def prepare_noaa_rainfall_interim(raw: pd.DataFrame, retrieved_at: str) -> pd.DataFrame:
    """输入：NOAA CSV 的原始字符串 DataFrame，以及下载回执中的带时区获取时间。

    保留所有原始列。每条记录的非空 AA1–AA4 分别展开，不相加；全空时留一行缺失。
    新增 station_id、timestamp、rain_mm、interval_min、retrieved_at、source、quality_flag，
    以及 source_record_number/precipitation_slot/raw_precipitation_group 等追溯字段。
    DATE 依据官方格式文档第 5 页从 UTC 转为 Asia/Shanghai，输出 ISO 8601 +08:00。
    LATITUDE/LONGITUDE 原样保留；CRS 尚未明确，不生成最终 lon/lat 或进行空间转换。
    """
    if raw.empty or not REQUIRED.issubset(raw.columns):
        raise ValueError("NOAA 原始表为空或缺少必要字段")
    slots = [name for name in ("AA1", "AA2", "AA3", "AA4") if name in raw.columns]
    if not slots:
        raise ValueError("NOAA 表没有 AA1–AA4 降水字段，需要检查数据源")
    for field in REQUIRED | set(slots):
        if any(not isinstance(v, str) for v in raw[field]):
            raise ValueError(f"{field} 必须使用字符串读取，空值保留为空字符串")
    acquired = datetime.fromisoformat(retrieved_at)
    if acquired.tzinfo is None or acquired.utcoffset() is None:
        raise ValueError("retrieved_at 必须来自下载回执且包含时区")
    acquired_text = pd.Timestamp(acquired).tz_convert("Asia/Shanghai").isoformat()
    rows = []
    for number, record in enumerate(raw.to_dict("records"), start=1):
        base = dict(record)
        station = record["STATION"]
        base.update(station_id="NOAA_ISD_" + station, source=SOURCE,
                    source_record_number=number, retrieved_at=acquired_text,
                    coordinate_crs="coordinate_crs_unknown", source_timezone="UTC")
        flags = ["coordinate_crs_unknown", "historical_archive"]
        if not re.fullmatch(r"\d{11}", station):
            flags.append("station_id_invalid")
        for field, limit in (("LATITUDE", 90), ("LONGITUDE", 180)):
            try:
                coordinate = float(record[field])
                if not math.isfinite(coordinate) or abs(coordinate) > limit:
                    raise ValueError("坐标范围无效")
            except ValueError:
                flags.append("source_" + field.lower() + "_invalid")
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", record["DATE"]):
                raise ValueError("源时间格式变化")
            observed = datetime.strptime(record["DATE"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            base["timestamp"] = pd.Timestamp(observed).tz_convert("Asia/Shanghai").isoformat()
            if observed > acquired:
                flags.append("observation_after_retrieval")
        except ValueError:
            base["timestamp"] = None
            flags.append("source_time_parse_error")
        present = [slot for slot in slots if record[slot].strip()] or [""]
        for slot in present:
            raw_value = record[slot] if slot else ""
            parsed = parse_precipitation_group(raw_value)
            row = dict(base)
            row.update({k: v for k, v in parsed.items() if k != "flags"})
            row.update(precipitation_slot=slot, raw_precipitation_group=raw_value,
                       quality_flag=";".join(flags + parsed["flags"]))
            rows.append(row)
    result = pd.DataFrame(rows)
    result["rain_mm"] = result["rain_mm"].astype("Float64")
    result["interval_min"] = result["interval_min"].astype("Int64")
    # 不同累计时段不当成同一记录；即便相同也不擅自删除或选最后一条。
    valid = result["timestamp"].notna() & result["interval_min"].notna()
    groups = result.loc[valid].groupby(["station_id", "timestamp", "interval_min"])["rain_mm"]
    sizes = groups.transform("size")
    distinct = groups.transform("nunique")
    result.loc[sizes.index[sizes.gt(1)], "quality_flag"] += ";duplicate_station_time_interval"
    result.loc[distinct.index[distinct.gt(1)], "quality_flag"] += ";conflicting_rain_values"
    return result.sort_values(["station_id", "timestamp", "interval_min", "source_record_number", "precipitation_slot"],
                              na_position="last").reset_index(drop=True)


def summarize_noaa_rainfall(table: pd.DataFrame) -> dict:
    """报告的是展开后的降水组及缺失占位行；原气象记录数单独统计。"""
    times = table["timestamp"].dropna()
    values = table["rain_mm"].dropna()
    fitness_limits = ["historical_archive_not_current_feed"]
    if table["station_id"].nunique() == 1:
        fitness_limits.append("single_station_not_citywide_rainfall")
    if not table["interval_min"].eq(60).any():
        fitness_limits.append("no_one_hour_precipitation_in_downloaded_sample")
    return {
        "raw_weather_record_count": int(table["source_record_number"].nunique()),
        "interim_row_count": len(table),
        "reported_precipitation_group_count": int(table["precipitation_slot"].ne("").sum()),
        "weather_records_without_precipitation_group": int(table.loc[table["precipitation_slot"].eq(""), "source_record_number"].nunique()),
        "station_count": int(table["station_id"].nunique()),
        "timestamp_start": None if times.empty else times.min(),
        "timestamp_end": None if times.empty else times.max(),
        "interval_min_counts": {str(k): int(v) for k, v in table["interval_min"].dropna().value_counts().items()},
        "interval_unknown_count": int(table["interval_min"].isna().sum()),
        "rain_missing_count": int(table["rain_mm"].isna().sum()),
        "rain_missing_rate_in_interim": float(table["rain_mm"].isna().mean()),
        "reported_rain_min_mm": None if values.empty else float(values.min()),
        "reported_rain_max_mm": None if values.empty else float(values.max()),
        "negative_rain_count": int(table["rain_mm"].lt(0).sum()),
        "quality_flag_counts": table["quality_flag"].str.split(";").explode().value_counts().to_dict(),
        "raw_records_removed": 0,
        "standard_interface_status": "blocked",
        "blockers": ["coordinate_crs_unknown", "precipitation_condition_semantics_require_review"],
        "fitness_limits": fitness_limits,
    }
