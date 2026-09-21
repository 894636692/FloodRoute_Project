# 冻结参数扩展验证预注册协议

协议版本：1.0  
协议日期：2026-09-21  
工程稳定基线：`v1.2.0` / `0f4f9a2b5e83a9ec0f051a6826731e749d356434`  
协议父提交：`d58f069`（历史验证已完成；不改变模型参数）  

本文件及 `results/expanded_validation/protocol.json` 必须在生成 Phase C 结果前提交。结果生成后不得根据方法表现修改本协议；如因实现错误必须修改，只能新增 protocol v2 并说明原因，不能覆盖本版本。

## 1. 冻结参数

唯一参数文件：`config/selected_v1_1.json`  
SHA256：`3f8ea08239d12d19b801afec28b5156625dd08daef4f54ff72573756bd7e6dd5`

禁止参数选择、校准、验证集调参和 winner tuning。`water.active=false` 保持不变。所有结果属于 `frozen external stress validation`。

## 2. 正式数据边界

- 道路：`data/derived/static/road_static_features.gpkg` 的完整机动车网络，保留 `(u,v,key)`。
- 降雨空间：真实深圳 4,232 个格网中心。
- 降雨数值：受控模拟强迫，只用于鲁棒性实验，不冒充历史观测。
- Truth 仅用于离线评价和生成配对观测；不得进入规划请求、参数或 Trigger 决策。

## 3. 新场景家族

每个家族使用 12 个时间步，15 分钟一步，起点为 `2023-09-07T12:00:00+08:00`。`rain_mm` 表示前一小时累计量。

1. `moving_center`：单一强降雨中心从研究区西南向东北线性移动；空间宽度为归一化范围的 0.13，时间幅度固定序列 `[8,15,28,45,70,100,125,145,150,135,105,75]` mm。
2. `dual_center`：两个强降雨核心同时发展，一个位于西北、一个位于东南；两核心强度在时间上错峰，避免退化为原 T1/T2 的单一静态雨团。
3. `anisotropic_band`：狭长各向异性雨带由西向东穿越研究区，长短轴比固定为 5:1，方位角随时间小幅旋转。

三个家族均不读取道路 ID，不以目标替代路线为中心，也不编码希望哪种方法获胜。

## 4. 随机种子

场景与观测种子固定为：

`7101, 7102, 7103, 7104, 7105, 7106, 7107, 7108, 7109, 7110, 7111, 7112`

这些种子不与 4101、4102、5101、5102、6101、6102、6103、8801 重复。OD 选择种子固定为 `7201`；方法运行顺序种子固定由 family、scenario seed、OD、time、delay、missing、noise 的稳定哈希派生。

## 5. 起终点生成

自动生成 8 组固定 OD，输出 `results/expanded_validation/od_pairs.csv`。规则在看结果前固定：

1. 从正式有向机动车图的最大弱连通分量取节点；
2. 按 UTM 坐标把起点候选分成西北、东北、西南、东南四个象限；
3. 对八个预定义方向 `E,W,N,S,NE,SW,NW,SE`，用种子 7201 打乱对应象限中的起点候选；
4. 对每个起点，按方向向量筛选目标候选并固定随机顺序；
5. 计算有向最短距离，接受第一个 3,000–15,000 m 的可达目标；
6. 不读取任何风险结果或方法表现，不人工替换表现不佳的 OD。

## 6. 决策时次

每个场景预先使用两个时次：

- `development`：第 4 个索引，即 13:00（开始后 60 分钟）；
- `high_risk`：第 8 个索引，即 14:00（开始后 120 分钟）。

时次不根据路线或风险结果选择。

## 7. 扰动与方法

- delay：`0, 30, 60` 分钟
- missing：`0, 0.3`
- noise：`0, 0.2`
- methods：`shortest, risk, risk_uncertainty, trusted`

同一 `family × seed × OD × time × delay × missing × noise` 的四种方法必须共享完全相同的 observation realization。方法顺序可以随机，但由稳定种子固定。

计划路线决策数：

`3 × 12 × 8 × 2 × 3 × 2 × 2 × 4 = 27,648`

27,648 行是配对重复测量，不称为 27,648 个独立样本。主要独立结构为 `scenario family × seed`。

## 8. 指标

主指标：长度加权 truth exposure：

`sum(length_i × truth_risk_i) / sum(length_i)`

保留：

- `distance_m`
- `truth_exposure`
- `max_truth_risk`
- `p95_truth_risk`
- `high_risk_length_ratio`
- `computation_ms`

辅助指标：

- `route_overlap_with_shortest`：与同一配对条件下最短路线的长度近似重合比例（按有向边长度的交集/并集计算）；
- `route_change_from_baseline`：是否与零延迟、零缺失、零噪声下同方法路线不同。

## 9. 汇总与置信区间

先在每个 `family × seed` 内对 OD、时次和扰动条件求平均，再跨 seed 汇总。方法比较固定为：

- `risk - shortest`
- `risk_uncertainty - risk`
- `trusted - risk`
- `trusted - risk_uncertainty`

对 family×seed 聚合值进行 2,000 次种子级 bootstrap，bootstrap 随机种子固定为 `7301`，输出平均差与 95% percentile CI。禁止直接把 27,648 行当作独立样本 bootstrap。

## 10. Trigger 压力测试

参数继续读取冻结配置。固定抽取每个家族的 seeds `7101, 7106, 7112`，每个 seed 使用 OD `OD01–OD04`，共 36 个事件 replay。观测扰动固定为 delay=30 分钟、missing=0.3、noise=0.2；逐个 12 时间步比较：

- `never`：不重规划
- `always`：每次尝试重规划
- `triggered`：冻结 Trigger

输出平均 truth exposure、replan_count、route_change_count、computation_ms，并保留该换路未换、轻微波动频繁搜索和连续换路等失败案例，不删结果。

## 11. 输出

固定输出目录 `results/expanded_validation/`：

- `protocol.json`
- `config_snapshot.json`
- `config_sha256.txt`
- `scenario_manifest.csv`
- `od_pairs.csv`
- `routes.parquet`
- `seed_summary.csv`
- `family_summary.csv`
- `method_comparisons.csv`
- `bootstrap_ci.csv`
- `trigger_summary.csv`
- `reproducibility.json`

报告：`docs/EXPANDED_FROZEN_VALIDATION.md`。所有图使用中文，并明确误差线是种子间标准差还是种子级 bootstrap 95% 置信区间。
