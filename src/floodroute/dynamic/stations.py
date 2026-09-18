"""把官方三列站点名录整理成中间表；缺少坐标，不能作为最终空间接口。"""

import pandas as pd


RAW_FIELDS = ["测站编码", "测站名称", "站类"]
TYPE_MAP = {
    "内涝水情站": "waterlogging",
    "河道水位站": "river_water_level",
    "水库水位站": "reservoir_water_level",
}
SOURCE = "深圳市政府数据开放平台/深圳市水务局"


def prepare_station_interim(raw: pd.DataFrame) -> pd.DataFrame:
    """输入：测站编码、测站名称、站类三列，均须以字符串读取。

    输出保留全部行及三个原始字段，并添加：
    station_id/name/station_type/source/coordinate_crs/quality_flag（字符串），
    lon/lat（可空浮点数，全部缺失），source_record_number（从 1 开始的数据行号）。
    编码和名称原样复制，不转为数字、不去重；类型只按 TYPE_MAP 映射。
    此名录不含时间，不生成观测时间或 retrieved_at，也不执行坐标转换。
    """
    if list(raw.columns) != RAW_FIELDS:
        raise ValueError(f"原始字段发生变化，需要重新核验：{list(raw.columns)}")
    for field in RAW_FIELDS:
        if any(not isinstance(value, str) for value in raw[field].dropna()):
            raise ValueError(f"{field} 必须按字符串读取，以免丢失编码前导零")

    result = raw.copy(deep=True).reset_index(drop=True)
    result["source_record_number"] = range(1, len(result) + 1)
    result["station_id"] = result["测站编码"].astype("string")
    result["name"] = result["测站名称"].astype("string")
    result["station_type"] = result["站类"].map(TYPE_MAP).fillna("unknown").astype("string")
    result["lon"] = pd.Series(pd.NA, index=result.index, dtype="Float64")
    result["lat"] = pd.Series(pd.NA, index=result.index, dtype="Float64")
    result["source"] = SOURCE
    result["coordinate_crs"] = "coordinate_crs_unknown"
    result["quality_flag"] = "coordinates_missing;coordinate_crs_unknown"

    # 每个异常都追加标记，不删除或修改原记录。
    for field, flag in [("station_id", "station_id_missing"), ("name", "name_missing")]:
        missing = result[field].fillna("").str.strip().eq("")
        result.loc[missing, "quality_flag"] += ";" + flag
    valid_id = result["station_id"].fillna("").str.strip().ne("")
    duplicate = valid_id & result["station_id"].duplicated(keep=False)
    result.loc[duplicate, "quality_flag"] += ";duplicate_station_id"
    result.loc[result["station_type"].eq("unknown"), "quality_flag"] += ";station_type_unknown"
    return result


def summarize_stations(table: pd.DataFrame) -> dict:
    """输入 prepare_station_interim 的结果；输出 JSON 可序列化的质量统计。"""
    ids = table["station_id"].fillna("")
    valid_ids = ids[ids.str.strip().ne("")]
    return {
        "record_count": len(table),
        "unique_station_ids": int(valid_ids.nunique()),
        "duplicate_id_extra_rows": int(valid_ids.duplicated().sum()),
        "duplicate_id_affected_rows": int(valid_ids.duplicated(keep=False).sum()),
        "missing_station_id": int(ids.str.strip().eq("").sum()),
        "missing_name": int(table["name"].fillna("").str.strip().eq("").sum()),
        "missing_lon": int(table["lon"].isna().sum()),
        "missing_lat": int(table["lat"].isna().sum()),
        "station_type_counts": table["station_type"].value_counts().to_dict(),
        "outside_shenzhen_count": None,
        "spatial_check_status": "not_checkable_without_coordinates",
        "rows_removed": 0,
        "standard_interface_status": "blocked",
        "blockers": ["coordinates_missing", "coordinate_crs_unknown"],
    }
