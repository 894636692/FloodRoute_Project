# Multisource Fusion V2 开发阶段记录

本文件只记录正式 confirmatory protocol 冻结前的机制检查与修改。开发种子固定为
9101–9104，OD 固定为 OD01、OD02；这些结果不得作为正式效果证据。

## D0：初始 V2 信息增益检查

- **问题**：初始 V2 虽加入了空间相关 `H_e` 和事件扰动 `B_e(t)`，但按相同 rain bin
  与 static susceptibility bin 控制后的 water 条件方差为 0.00507，低于 V1 的
  0.00757，未通过进入路由实验前的信息增益验收。
- **原因**：初始局部乘数的均值和动态范围偏小，主要压低了模拟积涝状态；隐藏变量存在，
  但对可观测 water index 的影响不足。该判断只使用 edge×time 信息统计，没有读取 OD、
  路线或 truth exposure。
- **修改**：将 retention multiplier 从 `0.65+1.70H+0.90B` 调整为
  `0.35+2.50H+1.20B`；将 inflow multiplier 从 `0.65+1.10H+0.80B` 调整为
  `0.25+2.40H+1.20B`。仍保持连续、空间平滑、固定种子，并保持输出在 [0,1]。
- **边界**：这是受控模拟 latent local hydrologic state，不代表深圳真实排水能力或水深。

后续机制检查及任何冻结前修改继续追加在本文件，不覆盖已有记录。

## D1：区分局部雨量与汇流驱动

- **问题**：D0 后条件方差仍为 0.00525，且独立局部状态主要作为局部 rain×static 的乘数，
  在低局部降雨道路上难以表达由邻域汇流造成的现场差异。
- **原因**：纯乘法形式仍要求本 edge 的 rain 较高，不能清楚表达“本地雨量相似、但区域汇流与
  局部排水状态不同”的机制。
- **修改**：流入目标拆成三项：`0.55*local_rain*static_susceptibility`、
  `1.20*regional_rain_mean*H`、`0.80*regional_rain_mean*B`，整体乘固定 inflow gain。
  区域平均雨量仅提供事件强迫；空间差异由预先生成的 H 与 B 决定。公式仍不读取 OD、路线或
  planner performance。

## D2：区域强迫统计量修正

- **问题**：D1 使用全域平均 rain 后，区域强迫被大量无雨格网稀释，V2 water 动态范围仍偏小；
  条件方差为 0.00466。
- **修改**：在保持同一机制结构的前提下，区域强迫固定为 edge rain 的 P90，表达事件中可用于
  邻域汇流的强降雨水平；局部项系数固定为 `0.90*P90*H + 0.65*P90*B`。P90 在所有场景中
  统一计算，未按路线或结果选择。

## D3：初始六类开发机制套件

固定 12 个 family×seed、2 个 OD 的结果：

- `water_stale_weight_lower_than_clean`：True
- `water_missing_fallbacks_to_rain_route`：True
- `water_degraded_weight_lower_than_clean`：True
- `rain_stale_increases_relative_water_weight`：True
- `missing_gap_to_rain_only`：0.0
- `clean_gain_vs_rain`：0.0

这些数值只验证方向，不作为 confirmatory 效果结论；本阶段未根据 truth exposure 修改参数。

## D4：稀疏传感器覆盖的重复惩罚

- **问题**：clean water 在道路上的平均 effective weight 只有约 0.054；reliability-aware 路线
  与 rain-only 完全相同。空间映射已经按传感器距离加权生成观测值，再在线性 reliability 中乘
  coverage，相当于对固定 48 点稀疏网络重复施加线性惩罚。
- **修改**：把可观察 reliability 从 `coverage*(1-quality)` 改为
  `sqrt(coverage)*(1-quality)`。该函数仍连续单调：coverage=0 时权重为 0，coverage 降低或
  quality 变差时权重严格不增加。修改依据是 source contribution 机制与固定 sensor coverage，
  没有根据某个 OD 的 exposure 调权。

## D5：clean source 的基础贡献标度

- **问题**：D4 后 clean water 的路线平均 effective weight 约 0.124，而 rain 为 1.0；固定稀疏
  sensor network 下，clean source 对 dynamic mixture 仍只有很小份额，无法检验第二源是否具有
  route-relevant information。
- **修改**：在 V2 实验策略中固定 `base_weight_rain=1`、`base_weight_water=3`。这是补偿固定
  sensor mapping 稀疏度的 source scale，不改变 static/dynamic 总权重，也不改变 production
  RiskEngine。陈旧、缺失和降质仍通过同一 freshness/reliability 公式连续降权。
- **决策规则**：只要求 clean high-quality water 形成非微小 contribution；没有以 exposure 改善
  或某个 OD 获胜作为参数选择标准。

## D4 后重跑：六类开发机制套件

固定 12 个 family×seed、2 个 OD 的结果：

- `water_stale_weight_lower_than_clean`：True
- `water_missing_fallbacks_to_rain_route`：True
- `water_degraded_weight_lower_than_clean`：True
- `rain_stale_increases_relative_water_weight`：True
- `missing_gap_to_rain_only`：0.0
- `clean_gain_vs_rain`：0.0

这些数值只验证方向，不作为 confirmatory 效果结论；本阶段未根据 truth exposure 修改参数。

## D5 后最终重跑：六类开发机制套件

固定 12 个 family×seed、2 个 OD 的结果：

- `water_stale_weight_lower_than_clean`：True
- `water_missing_fallbacks_to_rain_route`：True
- `water_degraded_weight_lower_than_clean`：True
- `rain_stale_increases_relative_water_weight`：True
- `missing_gap_to_rain_only`：0.0
- `clean_gain_vs_rain`：0.0004245065261637704

这些数值只验证方向，不作为 confirmatory 效果结论；本阶段未根据 truth exposure 修改参数。
