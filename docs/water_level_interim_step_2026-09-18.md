# C 模块：真实水位中间表

本步将已经下载的官方 CSV 整理为可复用的中间表，保留全部 100,000 行。没有调用 API，没有生成最终 water_level.csv。源时区、时间语义、水位测量基准及精确下载时间仍待确认，标准接口状态继续 blocked。

## 文件和运行方式

- 逻辑：`src/floodroute/dynamic/water_level.py`
- 入口：`scripts/prepare_water_interim.py`
- 测试：`tests/dynamic/test_water_level.py`
- 本次 CSV：`data/interim/dynamic/water_level_20260918T134047840190+0800/water_level_interim.csv`
- 本次报告：同目录 `quality_report.json`

在项目根目录的 PowerShell 执行：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_water_interim.py
```

每次创建带处理时间的新目录，不覆盖过去的输出。默认输入明确指向本次官方水位 CSV，以及上一步的站点中间表。也可以用 `--input` 和 `--stations` 指定其他已核验、结构相同的文件；输入路径必须分别位于项目的 raw/dynamic 和 interim/dynamic 内。原始水位文件仍保留在下载时的 stations 子目录中，没有移动。

## 输入和输出如何理解

`prepare_water_interim(raw, stations)` 输入两个 pandas DataFrame：

1. raw：测站编码、时间、水位（m）、水位id，全部以字符串读取，保留前导零和原文字。
2. stations：站点中间表，至少包含 station_id、name、station_type。编码必须非空且唯一，否则拒绝关联，避免一条水位被扩展成多行。

输出仍保留四个原始字段，并增加：

| 字段 | 类型和含义 |
|---|---|
| station_id | 字符串，复制测站编码 |
| source_record_id | 字符串，复制水位id；不是 station_id |
| source_record_number | 整数，从 1 开始的原始数据行序，可恢复原文件顺序 |
| name、station_type | 从站点中间表按 station_id 查得；未匹配则标记，不删记录 |
| source_time_without_timezone | 可空字符串，格式 YYYY-MM-DDTHH:MM:SS；只是无时区源时间，不是最终 timestamp |
| original_unit | m，来自官方源字段的明确单位 |
| water_level_cm | 可空浮点数，源米值乘 100；例如 0.01 m → 1 cm |
| retrieved_at | 当前全部空，手动下载的精确获取时间未核实 |
| source | 深圳市政府数据开放平台/深圳市水务局 |
| quality_flag | 用分号分隔的待核实项和逐行异常标记 |

解析时间时只对副本去掉首尾空白（含源时间前导制表符），四个原始字段保持原样。预期时间格式之外的值和无效日期会被标记；不会去掉意外出现的时区后缀再继续冒充正常值。

每行都标记 timezone_unknown、time_semantics_unverified、water_level_reference_unknown、retrieved_at_unknown。单位转换不改变“测量零点未知”这一事实，water_level_cm 不能当作道路积水深度。

输出按站点、解析后的源时间、原始行序排序，无效时间排在该站点末尾。同站同刻值相同、值冲突、包含不可解析数值的重复组分别标记，全部保留。无有效站点编码或时间的行不参加同站同刻判定，但保留且另行标记。

缺失或非法数值在派生数值列留空，原文字仍保留。负数保持原值并标记待审查。没有人为设定最大水位阈值，物理异常数量在报告中为 null。

报告里的 processed_at 是本程序处理时间（+08:00），不是观测时间或 retrieved_at。

## 本次验收结果

| 项目 | 结果 |
|---|---:|
| 记录数 / 删除数 | 100,000 / 0 |
| 测站数 / 已匹配内涝站数 | 148 / 148 |
| 原始四列缺失率 | 均为 0 |
| 时间解析失败 / 数值解析失败 / 负数 | 0 / 0 / 0 |
| 水位最小 / 最大 | 0 / 10 cm |
| 同站同刻重复组合 | 8,512 组 |
| 重复组合涉及记录 | 18,517 行，全部保留并标记 |
| 相比每组一行多出的记录 | 10,005 行 |
| 重复组数值冲突 | 0 |
| 排序 | 148 个站的原始输入均非升序；输出每站有效源时间均为升序 |

源时间范围为 2026-09-15T21:30:32 至 2026-09-18T00:57:23，无时区。不声称该范围内无缺测，也不声称覆盖完整历史。

5 项新增水位测试通过，连同 3 项站点测试共 8 项：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/dynamic -v
```

测试覆盖米到厘米转换、前导零、原值保留、排序、未知时间处理、缺失/无效/负数保留、重复冲突标记、未匹配站点，以及拒绝含重复编码的站点关联表。

另读取实际输出，按 source_record_number 恢复顺序后，四个原始字段逐值与源 CSV 一致；10 万个数值全部核对换算。两份输入 SHA-256 一致，原始水位 CSV/JSON/XML/XLSX/RDF 与上次验收哈希一致。B 组现有 derived 水位、降雨 fixture 与 Git HEAD 一致。

## 使用边界

这是本地中间数据，仅供质量检查、字段理解和后续标准化。尚不能作为最终观测接口或用于站点到道路的空间匹配。CSV 读取时指定 `dtype={"station_id": "string", "source_record_id": "string"}`，避免编码自动变成数字。

本步没有风险公式、延迟加工、观测窗口构造或 Ground Truth/Observed 划分。也没有推进降雨、预报、UI 或修改既有 GIS/路线脚本。
