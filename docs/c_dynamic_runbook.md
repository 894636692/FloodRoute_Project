# C 动态数据模块：运行和交接

最新进展：用户已确认深圳雨量时间定义，真实降雨候选已生成到 `data/derived/dynamic/shenzhen_grid/rainfall.csv`，共 100,000 行；全部累计量保留中间表。26 项动态测试通过。读取方法和剩余集成限制见[候选接口交接](shenzhen_rainfall_candidate.md)。以下旧阶段的元数据缺项描述由本段更新：深圳降雨时区/时间字段/累计方向已按用户确认解决，水务站点和水位未知项仍然独立保留。

目前已完成真实站点、水位样本的保留与中间清洗，以及 NOAA 历史降雨候选的解析。**最终真实动态 CSV 尚未通过验收，B 暂不能切换真实动态输入。** 最新状态看 [数据清单](dynamic_data_inventory.csv)；站点水位证据看 [阶段验收](dynamic_availability_acceptance_2026-09-18.md)，降雨证据看 [降雨核查](rainfall_source_check_2026-09-18.md)。

新增深圳实况格点样本已验收：100,000 条记录、4,232 个唯一格网，全部关联成功；官方页面截图已确认格网 WGS84/EPSG:4326，仍缺时区、实况时间字段和累计窗口定义，暂未生成中间标准表。详见[两表下载验收](shenzhen_rainfall_download_check_2026-09-18.md)，当前动态测试共 20 项。

## 本地复现

在 VS Code PowerShell 终端执行；这些命令只处理已有原件，输出到新的时间戳目录：

```powershell
Set-Location D:\codex\FloodRoute_Project
.\.venv\Scripts\python.exe scripts\prepare_station_interim.py
.\.venv\Scripts\python.exe scripts\prepare_water_interim.py
.\.venv\Scripts\python.exe scripts\prepare_noaa_rainfall_interim.py
.\.venv\Scripts\python.exe -m unittest discover -s tests\dynamic -v
```

默认路径对应已验收批次。水位脚本默认使用清单登记的站点中间表；若明确要用新批次，通过 `--stations` 指定刚生成的 stations_interim.csv。其他输入可用 `--input`，NOAA 同时用 `--receipt` 指定对应下载回执。不要手改 raw 文件，也不要把处理时间补成观测时间或历史获取时间。

输入 DataFrame 使用字符串保留站号前导零。`stations.py` 保留名录原列并补充类型和缺失坐标标记；`water_level.py` 将 m 乘 100 转为 cm、标记重复，时区未知则只保留无时区源时间；`rainfall.py` 解码 AA 组，UTC 转 +08:00，保留不同累计时段和异常。重要函数输入、输出与转换规则均在函数文档中。

正常结果：站点 485 行，水位 100,000 行，NOAA 降雨候选 8,877 行；质量报告显示 blocked 是当前数据定义缺失的真实结论，不是程序故障。20 项动态模块测试应通过。重复运行会生成新目录；清单记录的是已验收批次，不自动指向未经核验的新文件。

## 最终接口约定与 B 的现有要求

下列是待交付契约，**不是声明这些真实文件已经存在**。已阅读当前 `src/floodroute/common/schema.py`：为兼容 B，水位最终表还需要 lon/lat，降雨最终表还需要 retrieved_at；先记录在此，不修改 B 的算法。

| 目标文件 | 最终列 |
|---|---|
| stations.csv | station_id,name,lon,lat,station_type,source |
| water_level.csv | station_id,timestamp,water_level_cm,source,quality_flag,retrieved_at,lon,lat |
| rainfall.csv | station_id,timestamp,lon,lat,rain_mm,interval_min,source,quality_flag,retrieved_at |
| forecast_ensemble.csv（后续） | issued_at,valid_at,member_id,lon,lat,precipitation_mm,interval_min,source |

列名兼容不代表语义已满足：坐标必须有证据确认/转换为 EPSG:4326；观测与获取时间分别填写 ISO 8601 +08:00；降雨必须明确累计时段；水位必须说明基准，不能直接称道路积水深度。站号按字符串读取，推荐 `pd.read_csv(path, dtype={"station_id": "string"})`。若采用实况插值格点，必须另行约定格点 ID 与 spatial_type，不能混同实体测站。

所有异常在中间表保留并标记。B 当前质量标记及累计时段使用逻辑尚未与真实来源共同验收，不能把未知标记改为 valid 来通过接口。最终导出应先满足数据定义，再验收字段、坐标、时间、单位、重复与缺失处理。C 不构造延迟场景、不计算风险或不确定性。

当前 `data/derived/dynamic/water_level.csv` 和 `rainfall.csv` 仍是原有两行 fixture；不要将它们当作实测。`scripts/create_b_dynamic_fixture.py` 会写这两个路径，切换真实接口前须与 B 协调使用方式。

## 交接与阻塞项

raw/interim 已被 Git 忽略，包含原件的本地目录不会随代码 push。队友需从官方来源取得相同批次，或通过团队约定方式接收合法原件及哈希回执；本次未发送文件或替用户联系提供方。

1. 水务站点：需合法坐标来源及 CRS，目前名录不公开；不能按名称猜位置。
2. 水位：需确认 SJ 时区与时间语义、测量零点/水深含义；本批获取时间证据仍缺。问题已列入 [咨询草稿](dynamic_metadata_questions_2026-09-18.md)，尚未发送。
3. 深圳降雨：两份 CSV 已取得并归档，CRS 已由官方页面截图确认。现需元数据及剩余数据项说明，明确时区、实况时间字段和累计窗口。不要提供账号密码或 appKey；当前无需重新下载同样样本。
4. NOAA 备选：需要 CRS 和累计标记解释，且现有历史不与水位重叠；不作为当前实时源。

本轮没有修改 GIS 核心结果、OSM 图或 B 路线脚本，也未开发 UI。集合预报仍为明确推迟阶段。
