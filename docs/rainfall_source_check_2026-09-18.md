# 实况降雨来源与候选历史档案验收

核查日期：2026-09-18。结论：深圳本地实况降雨尚未取得可验收样本；已实际下载并解析 NOAA 宝安站历史档案，但仍不能交付正式 rainfall.csv。

后续更新：用户已提供深圳两表，现已归档并验收 100,000 条格点记录及 4,232 个格网，详见[深圳两表下载验收](shenzhen_rainfall_download_check_2026-09-18.md)。下文保留获取前的来源核查过程；“尚未取得”不再代表当前状态，最终接口仍因元数据缺项 blocked。

## 深圳官方渠道

深圳市气象局的[下载渠道答复](https://weather.sz.gov.cn/gkmlpt/content/12/12849/post_12849337.html)说明，公众网天气查询页面不支持数据下载，下载应使用深圳市政府数据开放平台或中国气象数据网。

气象局[格点匹配说明](https://weather.sz.gov.cn/gkmlpt/content/12/12737/post_12737911.html)要求先从“深圳范围自动站实况格点信息表”取得经纬度与格点编号的对应关系，再与“深圳范围自动站实况格点数据表”关联。候选目录入口：

- [实况格点信息表](https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_00903510)
- [实况格点数据表](https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_00903509)
- [市气象局开放数据目录](https://opendata.sz.gov.cn/data/dataSet/toDataSet/dept/9)

两个具体目录编号来自检索线索；本次访问只能读到平台外壳，尚未在登录后的完整页面核实目录名称、字段或下载包。若入口变更，应在部门目录按完整名称检索，不根据编号猜 API。本地公开请求遇到 HTTP 403；未绕过登录，也未尝试复制浏览器凭据。

气象局[数据性质说明](https://weather.sz.gov.cn/gkmlpt/content/11/11668/post_11668623.html)明确，这种 1 km 格点产品由自动站观测通过反距离加权插值得到。因此它是观测衍生格点产品，格点编号不能当成实体雨量站编号；若后续选用，应明确 spatial_type=interpolated_observation_grid。

气象局[日雨量口径说明](https://weather.sz.gov.cn/gkmlpt/content/12/12494/post_12494137.html)将日雨量定义为前一日 20 时至当日 20 时、北京时间。这仅支持该产品口径，不能用于推断水位 SJ 的时区或其他降雨字段的累计时段。

当前状态为 blocked / source_reviewed：需要用户在已登录平台下载两张表及元数据，优先选择包含现有水位日期的历史样本。收到后核实 CRS、时区、累计时段、单位、格点匹配与可用历史；尚未确认这些产品是否能导出该时间段。

## 已实际取得的 NOAA 候选

来源为 [NOAA NCEI Integrated Surface Database](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database)，本次直接取得[2025 年 59493099999.csv](https://www.ncei.noaa.gov/data/global-hourly/access/2025/59493099999.csv)，HTTP 200，无须登录或 API Key。

- 原始站名：BAOAN INTERNATIONAL, CH；原始站号：59493099999。
- 原始文件：`data/raw/dynamic/rainfall/noaa_isd_20260918T135237268402+0800/59493099999_2025.csv`。
- 获取时间：2026-09-18T13:53:16.887256+08:00，记录在同目录 download_receipt.json；它不是观测时间。
- SHA256：`6b8bbbe9c89317404912d204ec02b903e6a2f877953b9dc8d23fb8f4a2498f74`。
- 原始气象记录 7,465 条、40 列；源经纬度 113.810664、22.639258。已查格式文档给出角度单位，但尚未找到明确水平基准，故保留 coordinate_crs_unknown，不擅自声明 EPSG:4326。
- 观测范围转换为 +08:00 后为 2025-01-01T08:00:00+08:00 至 2025-08-25T05:00:00+08:00。这是下载快照的实际覆盖，不是完整 2025 年，也不是当前实况。

读取规则依据 [CSV 帮助](https://www.ncei.noaa.gov/data/global-hourly/doc/CSV_HELP.pdf)与 [ISD 格式文档](https://www.ncei.noaa.gov/data/global-hourly/doc/isd-format-document.pdf)：第 5 页定义观测时间为 UTC；第 13–14 页定义 AA1–AA4 降水组及条件/质量码。文档已保存到 `work/rainfall_source_check/noaa/`，相关页已渲染核对。

AA 组格式为“小时数,十分之一毫米数,条件码,质量码”：深度除以 10 得 mm，小时乘 60 得 interval_min。99 小时和 9999 深度都是缺失码，不能转换为 5,940 分钟或 999.9 mm。源 DATE 明确为 UTC，才执行 UTC → Asia/Shanghai；源字段仍原样保留。

## 实际质量检查

| 检查项 | 结果 |
|---|---|
| 中间表行数 | 8,877 |
| 非空 AA 降水组 | 3,286；不同累计时段分别保留，不相加 |
| 完全没有 AA 组的原气象记录 | 5,591；每条保留一行缺失占位，不当成零降雨 |
| 已知累计时段 | 360 分钟 125 行；720 分钟 125 行；1,440 分钟 1,874 行 |
| 未知累计时段 | 6,753 行，含上述 5,591 个占位行 |
| rain_mm 缺失 | 6,953 / 8,877 = 78.326%；分母是展开后的中间行，不是时间覆盖率 |
| 原编码可解数值 | 0–169.4 mm；仅说明解码结果，不代表全部物理有效 |
| 特殊标记 | 1,377 行为累计开始且带数值，6 行微量降水，12 行源 QC 可疑 |
| 删除记录数 | 0 |

本次所有正雨量组均带 condition=3。文档将 3 定义为累计开始（累计结束前数值缺失），与该样本仍有数值的现象需要进一步解释；不能仅凭 quality=1 就忽略条件码。代码保留值、原编码和 accumulation_begin_with_value_review 标记，不将其导出为已验证正式观测。

中间表及报告：

- `data/interim/dynamic/rainfall_noaa_20260918T140132318183+0800/rainfall_interim.csv`
- 同目录 `quality_report.json`
- 读回验收：`outputs/dynamic/rainfall_readback_acceptance_2026-09-18.json`

逐行验收确认可恢复全部 7,465 行原始 40 列，原文件及下载回执哈希不变。原有两个 source=fixture 的派生 CSV 与 Git HEAD 一致。

## 使用边界和下一项输入

该档案适合练习真实格式解析及质量检查。它只有一座机场站，没有逐小时降雨组，与 2026 年深圳水位没有时间交集；还缺明确 CRS 和累计标记解释。最终接口 status=blocked、processing_stage=interim_ready。不能作为深圳中心城区当前道路降雨真值，也不能用它填补水位缺失或制造配套实验。

下一项必要输入是深圳官方格点信息表、格点数据表和各自元数据/字段说明，或同平台有公开坐标的实测雨量站与时间序列。先核验能否获取，再决定是否适用。天气预报/集合预报遵循原计划，待站点、水位、实况降雨接口可用后再接入。
