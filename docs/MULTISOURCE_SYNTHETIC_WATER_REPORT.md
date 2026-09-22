# 异步多源可信机制受控验证报告

## 1. 为什么需要这个实验

已有研究验证只包含降雨动态源，无法独立检验不同数据源更新时间、延迟、缺失和质量对 Freshness、Uncertainty、Trusted Risk 与 Trigger 的作用。本实验加入一个可重复的**模拟积涝监测源**，研究问题是：异步多源条件下，显式时效与不确定性建模能否减轻陈旧或低质量第二数据源对路径规划与触发式重规划的负面影响。

## 2. 与真实水位的区别

本实验没有深圳真实水位。`water_level_index` 是 `[0,1]` 无量纲积涝状态指数，不是厘米水深、实测水位、历史水位恢复或水动力预测。真实生产配置与历史验证配置继续保持 `water.active=false`。所有正式输出分别标识 `SIMULATED_SCENARIO`、`SIMULATED_TRUTH` 和 `SIMULATED_WATER_SENSOR`。

## 3. 模拟水源生成机制

道路静态易涝程度固定为：

`S = clip(0.35×low_elev + 0.25×flatness + 0.30×builtup + 0.10×(1-vegetation), 0, 1)`。

每 5 分钟内部积分一次：降雨输入经 `1.35×rain×S` 转为目标积涝状态，道路依 `tau = clip(45 + 75×flatness + 45×builtup - 30×vegetation, 30, 180)` 分钟平滑累积和消退。它能产生相对降雨的滞后与雨停后逐步衰减，但不是物理水深模型。

## 4. 传感器布设

48 个虚拟传感器由固定 seed `7401` 选择。研究区在 EPSG:32650 中分为 4×4 空间层，每层按静态易涝程度 low/medium/high 三分位各取一条机动车道路边。选择过程不读取 latent truth、路线或方法结果。完整注册表位于 `data/scenarios/multisource_water/sensor_registry.csv`。

## 5. 异步时间机制

降雨 cadence 为 15 分钟。水传感器 cadence 为 10 分钟，三组 offset 分别为 0、3、6 分钟。降雨 Freshness 使用冻结的 `tau_rain=60 min`；分数据源方案使用预先存在的 dormant `tau_water=20 min`；统一时间尺度消融把两个源都设为 60 分钟。

## 6. 延迟

主实验固定使用 0、10、30、60 分钟延迟。`timestamp` 表示观测代表时间，`retrieved_at=timestamp+delay` 表示规划器真正可读取的时间。映射函数只使用 `retrieved_at <= decision_time` 的记录。

## 7. 缺失

主实验使用独立 dropout，固定组合覆盖 0、0.2、0.5 缺失率。缺失只发生在 observed 数据；latent truth 始终保留用于离线评价。无可用传感器时输出 `value=NaN, coverage=0`，不把未知当作 0。Trigger 另测东半区传感器 block outage 和恢复。

## 8. 噪声

主实验固定组合覆盖 sigma 0、0.05、0.15 的零均值高斯噪声，并 clip 到 `[0,1]`。随机数由场景、seed、决策时刻和条件共同确定，六种方法共享完全相同的 observation realization。

## 9. Freshness

source-specific 方案分别计算 `exp(-age_rain/60)` 和 `exp(-age_water/20)`。统一 tau 方案对二者都使用 60 分钟。参数在结果生成前提交，未根据结果调整。

## 10. Uncertainty

实验复用现有通用 RiskEngine。距离映射覆盖率、missingness 和只基于可观测状态生成的 quality flag 自然进入 uncertainty。质量标签不读取真实误差，因此不存在 oracle 质量信息。

## 11. Truth/Observed 隔离

完整 latent water 只由 observation generator 与 offline evaluator 使用。Planner 只接收 1,000 米内有限传感器经过 `exp(-distance/400)` 加权后的 `value,age_min,coverage,quality`。单元测试同时检查 runtime 不导入 `latent_ponding_truth`、observed 表不保留 truth 字段、未来 `retrieved_at` 不可见。

## 12. 实验协议

协议在 commit `50dddc7` 先于结果预注册。实验使用 3 个既有场景家族、12 个新 seed（8101–8112）、冻结的 8 组 OD、两个决策时刻、8 个预注册水观测条件和 6 种正式方法。独立统计单位为 `scenario family × seed`；OD、时刻和条件是配对重复测量。主实验产生 27,648 条六方法路线，另有 576 条 perfect-water 上界参考，共 28,224 条。

## 13. 方法

- `shortest`：最短路径；
- `rain_risk`：仅降雨风险；
- `multisource_naive`：降雨与水观测，不使用不确定性或 stale penalty；
- `multisource_uncertainty`：加入 uncertainty，不加入 freshness stale penalty；
- `trusted_universal_tau`：uncertainty + 统一 60 分钟 tau；
- `trusted_source_specific_tau`：uncertainty + rain 60 / water 20 分钟 tau；
- `perfect_water_reference`：规划器直接获得完整道路水 truth 的机制上界参考，只在单独消融中使用。

## 14. 主结果

全部家族的平均 truth exposure：

| 方法 | 平均值 |
|---|---:|
| rain-only risk | 0.420254 |
| perfect-water reference | 0.420649 |
| naive multisource | 0.423853 |
| multisource + uncertainty | 0.425196 |
| trusted source-specific tau | 0.425511 |
| trusted universal tau | 0.425578 |
| shortest | 0.446172 |

因此，本实验没有支持“加入模拟积涝源即可降低风险暴露”。最短路径仍然最高，但这是既有问题，不是本轮主要比较。

## 15. Ablation 与 seed-level bootstrap

差值均定义为左方法减右方法；负值表示左方法的 truth exposure 更低。跨三个家族的 12-seed bootstrap（2,000 次，seed 8301）结果：

| 比较 | 均值差 | 95% CI |
|---|---:|---:|
| perfect water − rain-only | +0.000395 | [+0.000181, +0.000638] |
| naive async − rain-only | +0.003598 | [+0.003194, +0.003984] |
| uncertainty − naive | +0.001343 | [+0.001190, +0.001493] |
| universal tau − uncertainty | +0.000383 | [+0.000315, +0.000456] |
| source-specific tau − universal tau | −0.000068 | [−0.000108, −0.000033] |
| source-specific trusted − rain-only | +0.005256 | [+0.004805, +0.005646] |

分数据源时间尺度相对统一时间尺度有很小但一致的改进；该改进不足以抵消 uncertainty/trusted cost 在本协议中的其他影响。即使 perfect-water reference 也未优于 rain-only，说明当前 truth 权重、planner source 权重和路径离散选择的组合没有呈现第二源潜在价值，不能据此声称真实水位无价值。

## 16. Trigger

七类压力事件、3 个家族、3 个固定 seed、2 个 OD、3 个策略共产生 378 条事件汇总和 4,536 条逐时记录。平均 truth exposure 为：always `0.429953`、never `0.433124`、triggered `0.433071`。Triggered 平均重规划 0.849 次、平均 planner calls 1.849 次；always 固定重规划 11 次、调用 12 次。因此 Trigger 仍体现风险暴露与计算次数之间的折中，没有整体达到 always 的风险水平。

## 17. Failure cases

预注册失败定义全部保留。共记录 924 条失败实例：

- `multisource_worse_than_rain_only`: 496；
- `trusted_worse_than_naive`: 279；
- `unnecessary_replan`: 85；
- `route_oscillation`: 36；
- `missed_useful_replan`: 22；
- `stale_source_induced_bad_route`: 6。

这些是逐配对实例计数，不是独立统计样本数。详细行保存在 `failure_cases.csv`，未删除失败 seed 或场景。

## 18. 统计不确定性

Bootstrap 使用 `scenario family × seed` 的 seed-level 均值，避免把 28,224 条路线误当成独立样本。CI 只描述本受控设计中的 seed 变化，不覆盖水动力模型误差、真实传感器误差或外部城市泛化。

## 19. 得到支持的结论

1. 受控模拟源能够通过现有 `value,age_min,coverage,quality` 接口稳定进入系统，而无需复制 RiskEngine。
2. source-specific tau 相对 universal tau 的平均 truth exposure 略低，bootstrap CI 在本设计内不跨 0。
3. Trigger 显著减少 planner calls，但与 always 相比存在风险代价。
4. 延迟、缺失、噪声和 block outage 能按预注册方式产生 freshness、coverage、quality 与 uncertainty 变化。

## 20. 没有得到支持的结论

1. 未支持 perfect water 相对 rain-only 的潜在路径收益。
2. 未支持 naive multisource 相对 rain-only 的总体收益。
3. 未支持 uncertainty 相对 naive 的总体风险降低。
4. 未支持完整 trusted source-specific 机制相对 rain-only 的总体收益。
5. 未支持 triggered 在风险暴露上优于 always。

这些否定结果按原协议保留，没有重新调 static/rain/routing/trusted/trigger 参数。

## 21. 与真实世界的边界

结论仅适用于此受控模拟机制、深圳真实道路/静态 GIS 几何和固定实验条件。它不证明深圳真实多源数据一定有效，也不证明真实水位提高或降低导航安全。本实验没有真实水位、物理厘米意义、真实传感器运维过程或水动力校准。现实结论仍需官方水位/积涝数据、明确坐标和时间语义、外部事件验证与现场安全评估。

