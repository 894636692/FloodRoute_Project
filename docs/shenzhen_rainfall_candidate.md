# 深圳真实格网降雨候选接口

已生成可由 pandas 读取的真实 CSV；状态为 parsed / candidate_ready_requires_integration_review。尚未替换 B 默认输入，也不表示 C 的水位与站点任务全部完成。

## 本次确认与数据解释

用户明确确认：“北京时间，前一小时累计量，剩下同理”，并指定截止字段“预报时间 FORECASTTIME”。因此 timestamp 来自原预报时间，按 Asia/Shanghai 本地化为 +08:00；不是把原字符串当 UTC 后平移八小时。RAIN01H 对应截至 timestamp 的前一小时累计，interval_min=60；window_start 为 timestamp 减一小时。窗口端点是否包含的离散采样约定未进一步声明，本次不做重采样。

定义来源单独标记 time_definition_user_confirmed，不冒称已取得官方时间说明。元数据配置：`docs/shenzhen_rainfall_metadata.json`，同时关联官方字段截图和 WGS84 证据。其他累计时段分别保留，不相加，不从累计量差分制造新时间序列。TRACERR01H 是预报字段，不作为实况。

坐标维持 EPSG:4326，无重投影。lon=(X1+X2)/2、lat=(Y1+Y2)/2 是已知矩形格网的算术中心；coordinate_role=grid_center_not_station。保留原角点，便于 A 使用格网范围做后续空间匹配。station_id 使用 `SZ_GRID_` 加原 GRIDID，是为兼容 CSV 字段名的格网唯一键，不是真实测站号。未生成假的 stations.csv。

## 产物

| 文件 | 内容 |
|---|---|
| data/derived/dynamic/shenzhen_grid/rainfall.csv | 100,000 行 1 小时累计降雨候选接口 |
| data/derived/dynamic/shenzhen_grid/grid_cells.csv | 4,232 个格网，保留原角点、格网 ID、代表点及来源 |
| data/derived/dynamic/shenzhen_grid/quality_report.json | 检查统计、元数据来源、输入哈希、未解决事项 |
| data/interim/dynamic/shenzhen_rainfall_20260918T145820222735+0800/rainfall_interim.csv | 全部原数据列、关联格网列，及 1/2/3/6/24 小时数值列 |

rainfall.csv 字段：

```text
station_id,timestamp,lon,lat,rain_mm,interval_min,source,quality_flag,retrieved_at,
grid_id,spatial_type,coordinate_role,window_start,source_record_id
```

```python
import pandas as pd
rain = pd.read_csv(
    "data/derived/dynamic/shenzhen_grid/rainfall.csv",
    dtype={"station_id": "string", "grid_id": "string", "source_record_id": "string"},
)
```

程序：`scripts/prepare_shenzhen_rainfall.py`，解析函数：`src/floodroute/dynamic/shenzhen_rainfall.py`。默认输出目录已存在，重复运行会拒绝覆盖。复现时显式指定一个不存在的新目录，例如：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_shenzhen_rainfall.py --output-dir data/derived/dynamic/shenzhen_grid_review_02
.\.venv\Scripts\python.exe -m unittest discover -s tests/dynamic -v
```

## 验收和边界

- 范围：2026-09-17T20:50:00+08:00 至 2026-09-18T00:40:00+08:00，24 个时次；最早时次仅 2,664 个格网，不是完整所选三天。
- 全部原始数据列读回一致、100,000 行保留；格网关联无缺失、时间解析无缺失，小时雨量无负值或空值，同格网同刻无重复。
- 这批小时雨量全部 0，只能验收格式和数据流程，不能检验强降雨风险表现。24 小时 0–0.3 mm 留在中间表，没有伪造强降雨。
- 精确下载时刻未知，retrieved_at 留空，全部记录带 retrieved_at_unknown；processed_at 仅是处理时间。
- 全部记录另带 interpolated_observation_grid 和 time_definition_user_confirmed；未标为无条件 valid。
- 26 项动态测试通过，包括不同发布时间和预报时间、跨日窗口、格网中心、单位、异常保留、重复和元数据约束。

B 现有读取器要求的列已具备，但它将位置按“测站最近点”处理，且只识别少量完整字符串质量标记，不能正确解释本接口的组合标记。B/A 需决定格网覆盖映射和这些质量状态的处理；本次不修改其风险或 GIS 算法，不自动运行真实数据路线实验。

根目录 `data/derived/dynamic/rainfall.csv` 和 `water_level.csv` 仍为原 fixture。清单 derived_path 现指向真实降雨候选子目录，避免覆盖现有可运行联调。最终全项目切换及站点/水位接口尚未完成。
