# 模拟积涝监测源多源机制验证预注册协议

协议版本：1.0  
预注册日期：2026-09-22  
基线：`v1.3.0-research` / `6d68a89f4c774270aee9430a012fdc5577cca47f`  
原冻结配置：`config/selected_v1_1.json`  
原文件 SHA256：`3f8ea08239d12d19b801afec28b5156625dd08daef4f54ff72573756bd7e6dd5`

本协议和 `results/multisource_synthetic_water/protocol.json` 必须在正式结果生成前提交。提交后不得依据结果修改设计；若发现会改变研究含义的协议错误，只能新增 v2 并说明原因，不能覆盖本协议。

## 1. 实验目的与真实性边界

研究问题是：当多个动态灾情信息源具有不同更新时间、延迟、缺失和质量时，信息时效性与不确定性建模能否减少陈旧或低质量第二源对风险感知路径规划和触发式重规划的不利影响。

数据类型严格分为：

- `REAL DATA`：真实深圳道路、地形、土地覆盖和气象格网位置；
- `SIMULATED SCENARIO`：三个受控降雨场景家族；
- `SIMULATED_TRUTH`：完整道路的 latent ponding index 和离线 truth risk；
- `SIMULATED_WATER_SENSOR`：有限虚拟传感器产生的延迟、缺失、带噪观测。

模拟水值名为 `water_level_index`，范围 `[0,1]`，是无量纲积涝状态指数。0 表示当前受控情景下无明显积涝状态，1 表示高积涝状态。它没有厘米水深含义，不是深圳真实水位、实测水深、历史水位恢复或水动力模型。

## 2. 版本与参数冻结

生产、历史与 UI 继续读取 `selected_v1_1.json`，其中 `water.active=false`。实验独立读取 `config/multisource_synthetic_water.json`，并要求：

- `experiment_only=true`；
- `source_kind=SIMULATED_WATER_SENSOR`；
- 仅实验配置把 water 设为 active；
- 静态权重、rain scale/weight/tau、routing alpha、trusted alpha、Trigger 阈值、最小改进和原 uncertainty 参数保持不变；
- 使用冻结配置中已有的 dormant water `weight=0.20` 和 `tau=20 min`；因为指数范围是 `[0,1]`，实验 water scale 固定为 1.0。

本阶段不执行 calibration、parameter selection 或 winner tuning。

## 3. Latent ponding truth

正式机动车道路边的静态易涝程度为：

`S_e = clip(0.35 low_elev_norm + 0.25 flatness_risk + 0.30 builtup_frac + 0.10 (1-vegetation_frac), 0, 1)`。

缺失静态分量使用既有显式先验 0.5。该公式只属于 synthetic latent generator，不写回 `static_risk`。

以 5 分钟内部步长进行一阶蓄泄积分。每个 15 分钟降雨状态在该区间内保持恒定：

`tau_e = clip(45 + 75 flatness_risk + 45 builtup_frac - 30 vegetation_frac, 30, 180) min`

`retention_e = exp(-5 / tau_e)`

`W_e(t+5) = clip(retention_e W_e(t) + (1-retention_e) × 1.35 × rain_truth_risk_e(t) × S_e, 0, 1)`

因此降雨上升时 W 滞后，降雨下降或停止后 W 逐步衰减，不会瞬间归零。`W` 是 `latent_ponding_truth`，不得被正式方法、RiskEngine 输入或 Trigger 读取。

离线评价风险固定为：

`multisource_truth_risk = clip(0.45 static_risk + 0.275 rain_truth_risk + 0.275 latent_ponding_truth, 0, 1)`。

动态真值内部等价于 rain 与 latent water 各 50%。权重在运行前固定，不根据路线表现调整。

## 4. 传感器网络

固定 48 个虚拟传感器，选择种子 7401。研究区按 EPSG:32650 划分 4×4 空间层；每层内按 `S_e` 的 low/medium/high 三分位各选一条正式机动车边，以固定随机顺序打破平局。选择只读取位置、拓扑和静态特征，不读取 latent truth、路线或方法结果。

传感器坐标取所选道路边中点并转换为 EPSG:4326。`sensor_registry.csv` 保存 `sensor_id,u,v,key,lon,lat,static_susceptibility,selection_stratum,selection_seed`。每个传感器读取对应道路边的 W 作为 `sensor_truth`；归档的 `latent_water_truth.parquet` 只保存传感器位置 truth，完整道路 truth 在单个场景内生成后仅供离线评价。

## 5. 异步时间、延迟、缺失、噪声与质量

降雨 cadence 为 15 分钟。water cadence 为 10 分钟，48 个传感器按 ID 循环分为 offset 0、+3、+6 分钟三组；非 5 分钟节点的 truth 由相邻内部积分状态线性插值。每条观测同时保存代表时间 `timestamp` 和可用时间 `retrieved_at = timestamp + delay`。决策时刻只能读取 `retrieved_at <= decision_time`。

正式 water delay 水平：`0,10,30,60` 分钟；missing：`0,0.2,0.5`；高斯零均值 noise sigma：`0,0.05,0.15`，之后 clip 到 `[0,1]`。Missing 只删除 observed 记录，不删除 truth，也不把缺失变成 0。主实验使用独立 dropout；Trigger 另有预注册 block outage。

质量标记只依据可观测实验状态，不读取真实误差：正常为 `good`；sigma 0.15 标记 `degraded_sensor_mode`；delay ≥30 标记 `communication_issue`；block outage 标记 `sensor_outage`。质量不是 oracle 误差标签。

观测字段固定为 `sensor_id,timestamp,lon,lat,water_level_index,interval_min,source,quality_flag,retrieved_at,source_record_id,source_kind`；source 为“受控模拟积涝监测源”，source_kind 为 `SIMULATED_WATER_SENSOR`。

## 6. 水源到道路的空间映射

距离计算全部在 EPSG:32650。每条机动车道路边使用 1,000 m 内可用传感器，距离权重 `w=exp(-distance/400)`；value、age 和 quality 按 w 加权。coverage 固定为 `clip(sum(w)/1.5,0,1)`。无传感器覆盖或无可用观测时，`value=NaN, coverage=0`，不能用 0 表示未知。

映射输出复用 RiskEngine 通用接口：`value,age_min,coverage,quality`。rain freshness 为 `exp(-age/60)`，water freshness 为 `exp(-age/20)`；统一 tau 消融把两者都设为 60 分钟。active-but-missing 与 inactive source 保持不同语义。

## 7. 场景、种子、OD 与决策时间

复用已预注册的三种场景算法：`moving_center,dual_center,anisotropic_band`，但使用从未参与旧实验的新种子 `8101–8112`。复用 `results/expanded_validation/od_pairs.csv` 中原先按拓扑、方向和距离自动选择的 8 个 OD，不重新挑选。决策时次固定为场景索引 4（发展期）和 8（高风险期）。

独立结构为 `scenario family × seed`；OD、时次、扰动和方法是配对重复测量。

## 8. 主实验条件与计算预算

完整 4×3×3 因子网格将产生 124,416 条主路线，每次完整重复预计超过一小时。为保证两次完整复现，本协议在看结果前固定 8 个覆盖全部水平的扰动组合：

| ID | delay | missing | sigma |
|---|---:|---:|---:|
| C00 | 0 | 0.0 | 0.00 |
| C01 | 10 | 0.2 | 0.05 |
| C02 | 30 | 0.5 | 0.15 |
| C03 | 60 | 0.2 | 0.15 |
| C04 | 10 | 0.5 | 0.00 |
| C05 | 30 | 0.0 | 0.05 |
| C06 | 60 | 0.5 | 0.05 |
| C07 | 0 | 0.2 | 0.15 |

主规模为 `12 seeds × 8 OD × 3 families × 2 times × 8 conditions × 6 methods = 27,648`。另在每个 family×seed×OD×time 运行一次 perfect-water 上限参考，共 576 条，总计 28,224 条路线。运行后不得删减 seed、场景或条件。

## 9. 方法与消融

六个正式配对方法：

1. `shortest`：纯距离；
2. `rain_risk`：water inactive，rain-only risk；
3. `multisource_naive`：rain+async water，risk cost 不加 uncertainty/freshness；
4. `multisource_uncertainty`：risk+uncertainty，关闭 stale penalty；
5. `trusted_universal_tau`：trusted cost，rain/water 均用 60 分钟 tau；
6. `trusted_source_specific_tau`：trusted cost，rain 60 分钟、water 20 分钟。

`perfect_water_reference` 是单独的机制上限：完整 latent water 在当前时刻以 coverage=1、age=0、quality=0 提供给 risk planner，只用于回答第二源理论上是否有信息价值。它不是正式可部署方法，不与异步方法共享“无 truth 输入”的声明。

固定比较：perfect water − rain-only、naive − rain-only、uncertainty − naive、universal tau − uncertainty、source-specific tau − universal tau、source-specific trusted − rain-only。不会只报告对 shortest 的比较。

## 10. 指标与统计

主指标为路线长度加权 `multisource_truth_risk`。同时记录 distance、max/p95 truth risk、high-risk length ratio、route overlap with shortest、route change 和 computation time。计时只用于工程统计。

机制指标预注册为：

- `stale_water_usage`：路线中 water coverage≥0.05、age>20 min 且归一化 water risk contribution≥0.025 的长度比例；
- `water_source_uncertainty`：路线长度加权的 `0.5(1-coverage)+0.15 quality`；
- `source_disagreement`：路线长度加权 `abs(rain_normalized-water_normalized)`，只在 water 有覆盖处计算；
- `trusted_penalty_due_to_staleness`：路线长度加权 `0.15 × (1-water_freshness)/2`；
- `trusted_penalty_due_to_uncertainty`：路线长度加权 `0.30 × uncertainty`。

先在 family×seed 内聚合，再用 seed 为单位做 2,000 次 bootstrap，固定 bootstrap seed 8301，输出 mean difference 和 percentile 95% CI。不得把所有路线行当独立样本。

## 11. Trigger 多源压力协议

固定使用三个家族、种子 `8101/8106/8112`、OD01/OD02 和完整 12 步，比较 never、always、triggered。七类事件为：自然 rain-down/water-high、water delay 60、东半区半数 sensors block missing、block outage 后恢复、water stale/rain fresh、rain stale 30/water fresh、预先指定传感器 degraded mode +0.15 bias 的 source disagreement。偏置属于已知 degraded mode，quality 不读取 truth error。

指标为平均 truth exposure、replan count、route change count、planner calls 和 computation time。失败定义在运行前固定：

- `missed_useful_replan`：triggered 平均 exposure > always +0.01；
- `stale_source_induced_bad_route`：water stale 时 source-specific route exposure > rain-only counterfactual +0.01；
- `unnecessary_replan`：一次触发换路在当前 truth 下没有降低 exposure；
- `route_oscillation`：路线在变化后返回此前使用过的非相邻 route digest；
- `trusted_worse_than_naive`：同配对条件 source-specific exposure > naive +0.01；
- `multisource_worse_than_rain_only`：同配对条件 naive exposure > rain-only +0.01。

所有失败案例必须进入 `failure_cases.csv`，不能删去或据此调参。

## 12. 防泄漏、测试与输出

正式六方法只能接收有限、延迟、缺失、带噪的 observed water；完整 latent truth 只能由 observation generator、显式 perfect reference 和 offline evaluator 读取。新增测试覆盖 W 范围/衰减/复现、静态响应、Truth/Observed 隔离、future retrieval、missing 语义、production/historical water inactive、实验配置边界、异步 cadence、freshness/tau、uncertainty、paired observations 和 Ground Truth import 隔离。

正式结果只写入 `results/multisource_synthetic_water/`，truth 只写入 `data/scenarios/multisource_water/`；不得覆盖 experiment_v2、expanded_validation 或 historical_validation。实验完整运行两次；排除 wall-clock/computation time 后，sensor layout、truth、observations、routes、aggregates、bootstrap 和 Trigger decisions 必须一致。

最终报告必须把支持、不支持和失败结果全部保留，并始终限定为 `CONTROLLED MULTI-SOURCE MECHANISM VALIDATION`，不能推断深圳真实水位有效性或现实应急导航安全性。
