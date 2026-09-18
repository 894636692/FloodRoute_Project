"""深圳格网实况接口整理。只做数据处理，不作道路匹配或风险计算。"""
import numpy as np
import pandas as pd

RAIN = {h: f"{h}小时累计降雨量（毫米）" for h in [1, 2, 3, 6, 24]}
BOUNDS = ["格网左下角经度（度）", "格网左下角纬度（度）", "格网右上角经度（度）", "格网右上角纬度（度）"]
SOURCE = "Shenzhen Meteorological Bureau / interpolated observation grid"
BASE_FLAGS = "interpolated_observation_grid;time_definition_user_confirmed;retrieved_at_unknown"


def normalize_shenzhen_rainfall(data, grids, metadata):
    """输入：原始中文列名、全字符串 DataFrame；有证据的 metadata 定义。

    返回 (interim, hourly, cells) 三个 DataFrame。
    interim 保留原数据所有列及关联的格网原列，另增 1/2/3/6/24 小时数值列。
    hourly 固定提供 station_id,timestamp,lon,lat,rain_mm,interval_min,source,
    quality_flag,retrieved_at；另保留 grid_id、源记录号、窗口起点及点位说明。
    cells 是格网名录，不是实体站点名录。station_id 仅为 B 接口兼容键，
    加 SZ_GRID_ 前缀；lon/lat 是 WGS84 角点算术中点，不进行坐标系转换。
    FORECASTTIME 按用户确认的北京时间本地化，不先当作 UTC 再平移八小时。
    缺失、负值、重复、非零预报时效均保留并标记；原始 DataFrame 不修改。
    """
    expected = {"crs": "EPSG:4326", "timezone": "Asia/Shanghai", "timestamp_field": "预报时间",
                "window_direction": "preceding", "time_definition_provenance": "user_confirmation"}
    if any(metadata.get(k) != v for k, v in expected.items()):
        raise ValueError("元数据未确认或与本解析器契约不一致")
    if metadata.get("retrieved_at") is not None:
        raise ValueError("此批获取时间未知；新批次获取时间需另行明确接入")
    required = ["格网ID", "预报时间", "发布时间", "入库时间", "预报时效（小时）", "预报级别", "记录编号"] + list(RAIN.values())
    if data.empty or grids.empty or not set(required).issubset(data) or not set(BOUNDS + ["格网ID（唯一）"]).issubset(grids):
        raise ValueError("原表为空或必要字段缺失")
    for frame in [data, grids]:
        if not all(frame[col].map(lambda v: isinstance(v, str)).all() for col in frame):
            raise ValueError("原字段必须全部按字符串读取")
    cells = grids.copy(deep=True)
    cells["grid_id"] = cells["格网ID（唯一）"].str.strip()
    if cells["grid_id"].eq("").any() or cells["grid_id"].duplicated().any():
        raise ValueError("格网主键为空或重复：不能建立可靠的多对一关联")
    coordinates = cells[BOUNDS].apply(pd.to_numeric, errors="coerce")
    left, bottom, right, top = [coordinates[col] for col in BOUNDS]
    valid = (pd.Series(np.isfinite(coordinates.to_numpy(dtype=float, na_value=np.nan)).all(axis=1), index=cells.index)
             & left.between(-180, 180) & right.between(-180, 180) & bottom.between(-90, 90)
             & top.between(-90, 90) & left.lt(right) & bottom.lt(top)).fillna(False)
    cells["lon"] = ((left + right) / 2).where(valid)
    cells["lat"] = ((bottom + top) / 2).where(valid)
    cells["station_id"] = "SZ_GRID_" + cells["grid_id"]
    cells["spatial_type"] = "interpolated_observation_grid"
    cells["coordinate_role"] = "grid_center_not_station"
    cells["crs"] = "EPSG:4326"
    cells["source"] = SOURCE
    cells["quality_flag"] = "interpolated_observation_grid"
    cells.loc[~valid, "quality_flag"] += ";invalid_grid_bounds"
    interim = data.copy(deep=True)
    interim["source_record_number"] = range(1, len(data) + 1)
    interim["grid_id"] = interim["格网ID"].str.strip()
    interim = interim.merge(cells.drop(columns=["quality_flag", "station_id"]), on="grid_id", how="left", validate="many_to_one", indicator=True)
    interim["station_id"] = "SZ_GRID_" + interim["grid_id"]
    interim["source"] = SOURCE
    interim["quality_flag"] = BASE_FLAGS
    interim.loc[interim["_merge"].ne("both"), "quality_flag"] += ";grid_not_found"
    interim.loc[interim["grid_id"].eq(""), "quality_flag"] += ";grid_id_missing"
    interim.loc[interim["lon"].isna() | interim["lat"].isna(), "quality_flag"] += ";coordinates_missing_or_invalid"
    # 格式检查不接受未知时区文本；源字段带制表符仅在解析视图中去除。
    text = interim["预报时间"].str.strip()
    naive = pd.to_datetime(text.where(text.str.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")),
                           format="%Y-%m-%d %H:%M:%S", errors="coerce")
    aware = naive.dt.tz_localize("Asia/Shanghai")
    interim["timestamp"] = aware.map(lambda t: t.isoformat() if pd.notna(t) else None)
    interim["window_start"] = (aware - pd.Timedelta(hours=1)).map(lambda t: t.isoformat() if pd.notna(t) else None)
    interim["retrieved_at"] = pd.NA
    interim.loc[naive.isna(), "quality_flag"] += ";source_time_invalid"
    lead = pd.to_numeric(interim["预报时效（小时）"], errors="coerce")
    interim.loc[lead.ne(0).fillna(True), "quality_flag"] += ";nonzero_or_invalid_forecast_lead"
    for hours, field in RAIN.items():
        values = pd.to_numeric(interim[field], errors="coerce")
        finite = values.notna() & np.isfinite(values)
        interim[f"rain_{hours}h_mm"] = values.where(finite).astype("Float64")
        interim.loc[~finite, "quality_flag"] += f";rain_{hours}h_missing_or_invalid"
        interim.loc[values.lt(0).fillna(False), "quality_flag"] += f";rain_{hours}h_negative"
    duplicate = interim["timestamp"].notna() & interim.duplicated(["grid_id", "timestamp"], keep=False)
    interim.loc[duplicate, "quality_flag"] += ";duplicate_grid_timestamp"
    interim = interim.drop(columns="_merge").sort_values(["station_id", "timestamp", "source_record_number"], na_position="last").reset_index(drop=True)
    interim["rain_mm"] = interim["rain_1h_mm"]
    interim["interval_min"] = 60
    hourly = interim[["station_id", "timestamp", "lon", "lat", "rain_mm", "interval_min", "source", "quality_flag",
                      "retrieved_at", "grid_id", "spatial_type", "coordinate_role", "window_start", "记录编号"]].copy()
    hourly = hourly.rename(columns={"记录编号": "source_record_id"})
    return interim, hourly, cells
