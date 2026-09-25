# Multisource Fusion V2 正式实验协议

状态：**在确认性结果生成前冻结**。协议基线为开发机制提交 `6d943eb`。包含本文件的 Git
提交即为 protocol freeze；精确 commit hash 将写入正式运行清单与最终状态文件。冻结后禁止
根据 9201–9212 的结果修改生成器、融合参数、路由参数、条件或失败阈值。

## 1. 研究边界

本研究是受控模拟实验。道路、DEM、WorldCover 和 OSM 几何来自项目既有数据；rain forcing、
latent local hydrologic state、event disturbance 与 water sensor observation 均为模拟数据。
`water_level_index` 是 [0,1] 无量纲状态指数，不是厘米水深，也不代表深圳真实排水能力。

旧 `synthetic_water_v1_redundant` 保留为消融基线。新
`synthetic_water_v2_local_state` 用来检验包含 rain/static 无法直接推断的现场状态时，第二动态源
是否具有决策价值。V1 结果目录保持只读。

## 2. Latent local hydrologic state

道路中点在 EPSG:32650 范围内归一化。固定 seed 9401 生成 12 个空间 anchors 与正态振幅，
通过长度尺度 0.18 的 RBF 加权得到低频空间场，再作固定 rank transform：`H_e∈[0,1]`。
函数不接受 OD、route 或 planner performance。

每个 scenario family×seed 由稳定哈希生成 1–3 个 disturbance patches。每个 patch 的位置、
宽度、振幅、开始、持续和两步恢复期在查看 OD/route 之前确定。`B_e(t)` 是 patch 的空间高斯
强度与出现/恢复时间函数的乘积，并裁剪到 [0,1]。

## 3. Water truth V2

积分步长 5 分钟。初始 water 为 0。已知静态易涝度沿用旧实验，不修改 production static risk。
在每个内部步：

```
tau_e(t) = clip(base_tau_e × (0.35 + 2.50 H_e + 1.20 B_e(t)), 15, 360)
retention_e(t) = exp(-5 / tau_e(t))
regional_rain(t) = P90(all-edge normalized rain at t)
target_e(t) = clip(1.35 × [
    0.55 local_rain_e(t) static_susceptibility_e
  + 0.90 regional_rain(t) H_e
  + 0.65 regional_rain(t) B_e(t)
], 0, 1)
water_e(t+5) = clip(retention_e water_e(t) + (1-retention_e) target_e, 0, 1)
```

P90 是对所有场景统一的区域强迫统计量，不按结果选择。

## 4. Sensor network 与 Observation

沿用独立 seed 7401 的 48 传感器，4×4 空间分层，每格按静态易涝度 low/medium/high 各取一
点。cadence 为 10 分钟，三组 offset 为 0/3/6 分钟。edge mapping 半径 1000 m，距离尺度
400 m，full weight 1.5。planner 只能收到 timestamp、retrieved_at、value、coverage 与由实验
状态声明的 quality；不得收到 H、B、完整 water truth 或 observed−truth error。

water quality penalty：normal=0，degraded/communication=0.5，missing=1。noise 与 bias 仅由
预注册条件产生。future `retrieved_at` 的观测不可见，missing 保持 unavailable，禁止当成 0。

## 5. Reliability-aware fusion

对 source `i∈{rain,water}`：

```
freshness_i = exp(-age_i / tau_i)
reliability_i = sqrt(coverage_i) × (1-quality_i)
availability_i = finite(value_i) and coverage_i > 0
w_eff_i = base_weight_i × freshness_i × reliability_i × availability_i
dynamic_risk = Σ(w_eff_i normalized_value_i) / Σ(w_eff_i)
```

base weights 为 rain=1、water=3；tau_rain=60 min、tau_water=20 min。S4 将二者 tau 均设为
60 min，S5 使用各自 tau。static weight=0.45、dynamic weight=0.55，沿用冻结 routing alpha。
当全部 dynamic effective weight≤1e-9 时输出 static-only。water 不可用而 rain 可用时公式自然
等于 rain-only；rain 不可用而 water 可用时由 water 驱动。confidence 为各源
`freshness×reliability×availability` 的均值，不把低可靠状态伪装成高可信。

## 6. 正式设计

- Scenario families：moving_center、dual_center、anisotropic_band。
- Confirmatory seeds：9201–9212；这些未用于开发。
- OD：`results/expanded_validation/od_pairs.csv` 中冻结的全部 8 对。
- Decision steps：4、8。
- 独立单位：scenario family×seed，共 36 个。
- OD、time、condition、method 是 paired repeated measurements。

8 个条件固定为：C00 clean；C01 water delay10/missing.2/noise.05；C02
delay30/missing.5/noise.15；C03 water delay60/missing.2/noise.15；C04 water missing=1；
C05 rain delay60、water fresh/noise.05；C06 water delay60/missing.5/noise.05；C07
water missing.2/noise.15 且固定前 16 sensors +0.15 bias。除 C05 外 rain delay=0。

方法：S0 shortest；S1 rain-only；S2 V1 redundant-water naive；S3 V2 local-state naive；
S4 V2 reliability-aware/universal tau；S5 V2 reliability-aware/source-specific tau；S6 perfect
water V2 reference。S6 仅离线机制上界，不进入 UI。

离线 truth objective 固定为：0.45 static + 0.275 normalized rain + 0.275 latent water V2。
planner 不读取该组合。

## 7. 指标与统计

主要指标是 length-weighted truth exposure。辅助指标为 distance、max/p95 truth risk、
high-risk length ratio、route overlap；机制指标为 rain/water effective weight mean、water P90、
fallback fraction、low-reliability water usage、source disagreement fraction 与 gain vs rain。

预注册派生量：

- `clean_source_gain = exposure(S5,C00)-exposure(S1,C00)`；负值表示收益。
- `bad_source_degradation = exposure(S5,C02/C03/C07)-exposure(S1,same)`。
- `fallback_gap_to_rain_only = exposure(S5,C04)-exposure(S1,C04)`。
- `stale_source_weight_ratio = stale source mean weight / its C00 mean weight`。
- `fresh_source_weight_ratio = fresh source weight / other stale source weight`。
- `disagreement_resolution = exposure(S5,C07)-exposure(S3,C07)`。

先按 family×seed 汇总所有 repeated measurements，再进行 seed-level paired bootstrap 2000 次，
bootstrap seed=9301，输出 mean difference 与 95% percentile CI。不得把 route rows 当独立样本。

## 8. Failure definitions

全部保留，不删除不利 seed：multisource worse than rain-only 与 trusted worse than naive 的阈值
均为 truth exposure +0.01；stale-source bad route 为 stale 条件下 S5 比 S1 高 +0.01；missing
fallback failure 为 C04 路线/暴露与 S1 差异超过 1e-9；bad-source overweighted 为坏条件 water
weight/clean weight>1；fresh-source underweighted 为 clean water weight≤1e-9。Trigger 的 missed
useful replan 阈值为 always exposure+0.01；unnecessary replan 与 route oscillation 按逐时路线记录。

## 9. Trigger v2

使用 seeds 9201、9206、9212 与 OD01、OD02，比较 never/always/triggered。七种 stress case：
rain 下降但 water 高、water 逐渐 stale、block outage、recovery、rain stale/water fresh、water
stale/rain fresh、sources disagreement。报告风险与 planner calls 的折中，不以单一排名定义成功。

## 10. UI 语义

只有“异步多源机制实验”可启用 `SIMULATED_WATER_SENSOR_V2`。真实深圳降雨场景继续显示“水位：
未启用”。地图与 source cards 必须明确 simulated/real、timestamp、retrieved_at、age、quality、
availability；missing 不显示为 0；water 只称“积涝状态指数”。persistent Leaflet map 实例不得
因 source 更新重建。S6 与 latent truth 不进入真实 UI。
