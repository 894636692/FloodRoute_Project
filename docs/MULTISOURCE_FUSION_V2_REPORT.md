# Multisource Fusion V2 正式研究报告

## 1. 第一版多源为什么没有成功

V1 water 与 rain 高度冗余，planner/truth 权重不一致，且道路网络只允许离散连通路线。V1 的
perfect water 也未优于 rain-only，说明问题不只是传感器噪声。

## 2. 诊断发现

V1 在 48,478,176 个 edge×time 样本上的 Pearson 为 0.6219；控制 rain decile 与 static
quintile 后条件方差为 0.00757。576 个路线配对中仅 57 个换路，风险排序 Spearman 为
0.9939。详见 `MULTISOURCE_V1_DIAGNOSIS.md`。

## 3. 为什么需要独立现场状态

若第二源只是 rain/static 的平滑变换，它不会增加 planner 已有信息。V2 因而引入 planner
不可见、sensor 可观测的空间相关局部状态 H 与事件扰动 B。

## 4. V2 latent local hydrologic state

H 来自固定 anchors 的 EPSG:32650 低频随机场；B 由 scenario+seed 决定 1–3 个出现、持续、
恢复的 patches。二者都不读取 OD、路线或实验结果，也不代表深圳真实排水设施。

## 5. 模拟水源生成

V2 保留降雨驱动、5 分钟累积、滞后与消退，并加入区域 P90 rain 对 H/B 的局部汇流驱动。
输出始终是 [0,1] `water_level_index`，不是物理水深。完整公式见冻结协议。

## 6. Truth / Observed 隔离

latent truth 只用于生成 48 个异步 sensor observation 与离线评价。planner 只接收 value、
timestamp、retrieved_at、coverage 和预声明 quality；测试确认 fusion API 没有 truth 参数。

## 7. Reliability-aware fusion

V2 用 `base × freshness × sqrt(coverage) × (1-quality) × availability` 控制 source contribution，
再归一化动态源。该策略相对 V2 naive 的平均 exposure 改善 **0.001918**，bootstrap 95% CI
**[-0.002084, -0.001748]**。

## 8. Freshness

rain tau=60 min，water tau=20 min。water delay 60 分钟时，S5 water mean effective weight 从
clean 的 **0.4770** 降到 **0.0072**。

## 9. Reliability

degraded 条件 water effective weight 为 **0.0359**，typical 为 **0.2606**。quality 只来自
normal/degraded/communication/missing 实验状态，不使用 observed−truth error。

## 10. Fallback

C04 water missing 时 water weight 精确为 0，S5 与 rain-only 的 mean exposure 都为
**0.430471**，没有 `missing_source_failed_to_fallback` failure。若全部动态源无效，代码明确
退化为 static-only。

## 11. Development 与 confirmatory 隔离

开发只使用 seeds 9101–9104 与 OD01/OD02。信息范围、稀疏 coverage 重复惩罚与 clean
contribution 的修改均记录在开发日志；确认性 seeds 9201–9212 从未用于修改参数。

## 12. Protocol freeze

协议提交为 **59da81f**。确认性运行后没有更改生成器、fusion、tau、routing、condition 或
failure threshold。

## 13. 正式方法

比较 S0 shortest、S1 rain-only、S2 V1 redundant naive、S3 V2 local naive、S4 reliability
universal tau、S5 source-specific tau，以及离线 S6 perfect V2 reference。正式主方法路线
27,648 条，S6 reference 576 条，总计 28,224 条。

## 14. Information gain

开发期相同 16,159,392 个 edge×time 样本中，V1/V2 Pearson 分别为 **0.5264/0.3370**，
Spearman 为 **0.5655/0.3759**，条件方差为 **0.00757/0.01121**。V2 low-rain/high-water
比例为 **0.4567%**，且 residual map 显示由 H/B 产生的空间结构。证据支持“存在独立信息”，
但不等同于证明路线收益。

## 15. Clean-source 结果

C00 中 rain-only、V2 naive、S5 exposure 分别为 **0.430471、0.433417、0.433278**。clean
water 改变了路线和风险排序，但没有降低总体 truth exposure。因此“clean multisource 有总体
收益”未获支持。

## 16. Stale-source 结果

C03 中 S5 为 **0.430508**，接近 rain-only **0.430471**，显著好于 naive **0.433366**。
说明 stale water 被有效降权，但仍出现 2 个 `stale_source_induced_bad_route` failure。

## 17. Missing-source 结果

C04 精确回到 rain-only，支持安全退化。

## 18. Noisy-source 结果

C02 S5 为 **0.430845**，比 naive **0.433364** 更接近 rain-only。可靠性机制减小坏源影响，
但不能保证每个配对都更优。

## 19. Source disagreement

C07 S5 为 **0.432037**，好于 naive **0.433358**，仍差于 rain-only **0.430471**。这支持
“降低损害”，不支持“分歧下多源优于单源”。

## 20. Trigger

never/always/triggered 的 exposure 分别为 **0.437542/0.430985/0.434785**，平均 planner calls
为 **1.00/12.00/1.77**。triggered 位于风险与计算量之间；保留 22 个 missed-useful、122 个
unnecessary-replan 与 11 个 oscillation failure。

## 21. Failure cases

总 failure 462：multisource worse than rain-only 236、trusted worse than naive 68、stale-source
bad route 2、bad-source overweighted 1，加上上述 Trigger failures。未删除任何不利 case。

## 22. Bootstrap

以 family×seed 为独立单位、seed bootstrap 2000 次。S5−rain 为 **+0.000958**，95% CI
**[+0.000841,+0.001092]**，明确不支持总体收益。S5−universal 为 **−0.000099**，CI
**[-0.000206,+0.000002]**，方向很小且区间触及 0。

## 23. UI

新增“异步多源机制实验”，显示 simulated rain、48 个 simulated sensor、timestamp、
retrieved_at、age、quality、availability、source cards 和融合详情。真实模式仍显示“真实水位
数据：未启用”。persistent Leaflet map 不重建，sensor layer 在原实例内更新。人工清单仍 pending。

## 24. 得到支持的结论

V2 water 确实包含 rain/static 无法完全解释的条件差异；freshness/reliability 能按预期降权；
missing water 可精确回到 rain-only；可靠性融合比 naive 更稳健；Trigger 提供 calls/exposure 折中。

## 25. 未得到支持的结论

不支持 V2 multisource 或 perfect-water V2 在总体上优于 rain-only；不支持 source-specific tau
具有明确非零总体优势；不支持所有坏源场景都没有个别劣化。

## 26. 真实世界边界

本研究没有真实深圳道路水位验证、真实堵塞点、泵站或排水能力。结果不能解释为真实水位一定
提高导航安全，也不能证明现实灾害中更安全。它只验证受控模拟源、融合机制与软件退化行为。
