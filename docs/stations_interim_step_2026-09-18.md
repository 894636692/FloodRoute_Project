# C 模块：站点中间表整理

本步完成三列官方名录到中间表的可重复转换。全部 485 行保留，其中内涝水情站 148、河道水位站 133、水库水位站 204。编码唯一且无空值；名称无空值。全部 485 行缺少经纬度，超出深圳范围数量无法核验，不记为 0。

## 运行

在项目根目录 PowerShell 执行：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_station_interim.py
```

脚本默认读取此前已验收的站点 CSV；也可用 `--input` 指定 `data/raw/dynamic/stations` 中另一份相同三列结构的 CSV。每次创建带处理时间的新目录，不覆盖历史结果。

本次输出：

- `data/interim/dynamic/stations_20260918T132952123614+0800/stations_interim.csv`
- 同目录 `quality_report.json`

## 看懂函数与字段

核心函数位于 `src/floodroute/dynamic/stations.py`，入口脚本位于 `scripts/prepare_station_interim.py`。

`prepare_station_interim(raw)` 输入是包含“测站编码、测站名称、站类”的 DataFrame，读取时全部使用字符串，避免把编码前导零丢掉。输出是一个新的 DataFrame，不修改输入。

| 输出字段 | 处理方式 |
|---|---|
| 测站编码、测站名称、站类 | 保留原始字段和值，便于逐条核对 |
| source_record_number | 从 1 开始的数据记录序号，不包括 CSV 表头 |
| station_id、name | 原样复制测站编码和测站名称 |
| station_type | 内涝水情站 → waterlogging；河道水位站 → river_water_level；水库水位站 → reservoir_water_level |
| lon、lat | 内存中为可空浮点数，CSV 中为空；没有填 0 或猜测位置 |
| source | 深圳市政府数据开放平台/深圳市水务局 |
| coordinate_crs | coordinate_crs_unknown；没有执行坐标转换 |
| quality_flag | 每行都有 coordinates_missing;coordinate_crs_unknown；若出现缺编码、缺名称、重复编码或未知站类，会追加标记 |

重复站名不等于重复测站。本步不按名称合并，也不丢弃重复编码记录；重复编码会被标记。未知站类保留原文字，映射为 unknown 并标记，而不擅自归入其他类别。

报告中的 `processed_at` 是本次程序处理时间（带 +08:00），不是测站观测时间，也不是下载时间。原始文件路径及 SHA-256 保存在报告中供追溯。

CSV 不携带数据类型。再次读取时至少明确指定编码类型：

```python
stations = pd.read_csv(csv_path, dtype={"station_id": "string", "测站编码": "string"})
```

## 验收及边界

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/dynamic -v
```

3 项测试通过，覆盖前导零、原值保留、坐标缺失、重复/缺失/未知类别保留并标记，以及输入结构或类型错误时明确拒绝。另对实际输出读回核验：485 行原始字段逐值一致，148 个 waterlogging，编码唯一，经纬度全部为空。原始 CSV SHA-256 未改变，现有 B 联调 water_level.csv 和 rainfall.csv 与 Git HEAD 一致。

这是站点中间表，不是最终 `data/derived/dynamic/stations.csv`。标准空间接口继续 blocked，等待明确且可使用的坐标及 CRS。可据 station_id 关联已下载水位记录进行非空间检查；不能进行点到道路匹配。没有处理水位时间、生成延迟场景或修改 GIS/算法代码。
