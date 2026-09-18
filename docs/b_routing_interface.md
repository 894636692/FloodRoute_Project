# B 路径算法模块接口说明

本文档只说明 B 组负责的路径算法、风险计算、Trigger 和实验指标接口。附件规划书是设计依据，真正联调时以这里的代码校验和字段名为准。

## 模块边界

B 负责：

- 读取 A 输出的静态道路特征。
- 读取 C 已清洗好的降雨、水位动态 CSV。
- 计算静态风险、动态风险、Freshness、Uncertainty、Trusted Risk。
- 基于 OSM 有向 `MultiDiGraph` 做 `shortest`、`risk`、`trusted` 三种路线规划。
- 输出给 C 可展示的路线 JSON。
- 运行 Trigger 与延迟场景实验，统计 `replan_count`、`route_change_count` 等指标。

B 不负责：

- 不重新下载 DEM、WorldCover、OSM 等 GIS 底层数据。
- 不直接解析政府原始接口。
- 不使用 Ground Truth 做实时规划。Ground Truth 只能用于离线评估。

## 坐标系约定

- 内部计算坐标系：`EPSG:32650`
- 前端/地图显示坐标系：`EPSG:4326`

## A 到 B：静态道路特征

文件建议路径：

```text
data/derived/static/road_static_features.gpkg
```

必需字段：

```text
u,v,key,geometry,length_m,highway,oneway,
elev_mean_m,elev_min_m,low_elev_norm,
slope_mean_deg,slope_p90_deg,flatness_risk,
builtup_frac,vegetation_frac,water_frac,source_version
```

关键约束：

- `u,v,key` 必须保留 OSM 原始有向边编号。
- B 使用 `networkx.MultiDiGraph`，不会把路网简化为无向图。
- `geometry` 必须是 `EPSG:32650` 下的线几何。

当前仓库中的 `scripts/prepare_b_static_fixture.py` 是临时联调脚本：它只把已有派生 OSM/DEM/WorldCover 数据整理成 B 需要的 A 输出格式，不重新下载 GIS 数据。

## C 到 B：动态观测数据

降雨文件字段：

```text
station_id,timestamp,lon,lat,rain_mm,source,retrieved_at,quality_flag
```

水位文件字段：

```text
station_id,timestamp,lon,lat,water_level_cm,source,retrieved_at,quality_flag
```

建议路径：

```text
data/derived/dynamic/rainfall.csv
data/derived/dynamic/water_level.csv
```

B 只读取 C 清洗后的标准 CSV，不解析政府原始 API。当前仓库中的 `scripts/create_b_dynamic_fixture.py` 只生成联调样例，后续可直接替换为 C 的正式输出。

## B 到 C：路线请求

示例：

```json
{
  "start_lon": 114.029285,
  "start_lat": 22.5248887,
  "goal_lon": 114.0816697,
  "goal_lat": 22.5388943,
  "timestamp": "2026-09-17T15:30:00+08:00",
  "mode": "trusted"
}
```

`mode` 可选：

- `shortest`：只按长度最短。
- `risk`：考虑静态和动态风险。
- `trusted`：在风险基础上叠加 Freshness 和 Uncertainty，更适合作为最终展示路线。

## B 到 C：路线响应

响应字段：

```json
{
  "route_id": "R-xxxx",
  "mode": "trusted",
  "distance_m": 6625.98,
  "travel_time_s": 828.25,
  "mean_risk": 0.9318,
  "max_risk": 1.0,
  "confidence": 0.1201,
  "triggered": false,
  "trigger_reason": "",
  "edge_ids": [[2323527539, 8071647108, 0]],
  "geometry_geojson": {
    "type": "LineString",
    "coordinates": [[114.029285, 22.5248887]]
  }
}
```

`edge_ids` 中每项都是 `[u, v, key]`，C 可以用它回查路线经过的 OSM 边。`geometry_geojson` 已转换为 `EPSG:4326`，可以直接给地图组件展示。

## 常用命令

准备 B 静态 fixture：

```powershell
python scripts\prepare_b_static_fixture.py
```

准备 C 动态 fixture：

```powershell
python scripts\create_b_dynamic_fixture.py
```

运行一次 B 路线规划：

```powershell
python scripts\plan_route_b.py
```

运行 Trigger 延迟实验：

```powershell
python scripts\run_b_trigger_experiment.py
```

运行测试：

```powershell
python -m unittest discover -s tests -v
```

