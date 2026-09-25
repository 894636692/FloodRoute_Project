# Multisource Fusion V2 最终状态

状态：**研究实现、冻结确认性实验、可复现性检查、自动化测试与多源 UI 实现均已完成；浏览器人工复核仍待用户完成。**

分支：`research/multisource-fusion-v2`

冻结协议提交：`59da81f`

冻结配置 SHA-256：`2259786b638f8162bb62abddb264a4160eda7ebe9f9cae10836e601c5451ae83`

## 1. V1 的主要问题

V1 water 大部分是 rain 与既有 static susceptibility 的累积变换，新增信息有限；同时存在
truth/planner 权重不一致与道路网络路线离散性。576 个 V1 配对中只有 57 个换路，风险排序
Spearman 达 0.9939。即使 perfect-water V1 也没有优于 rain-only，因此问题不只是传感器噪声。

## 2. Rain-water redundancy 有多高

V1 诊断的 Pearson 为 0.6219，Spearman 为 0.5655；控制 rain decile 与 static quintile 后的
water 条件方差为 0.00757，low-rain/high-water 比例仅 0.0354%。这些结果支持“V1 存在明显
source redundancy”。

## 3. V2 新增的独立信息

V2 增加空间相关 latent local hydrologic state `H_e` 与按 scenario×seed 预先生成的事件局部扰动
`B_e(t)`。二者由固定 seed、空间低频场和 1–3 个扰动 patch 产生，不读取 OD、路线或实验结果。
它们只代表受控模拟的局部排水/滞蓄差异，不代表深圳真实排水设施。

## 4. 独立信息是否真正存在

存在。相同 16,159,392 个 edge×time 样本中，V1/V2 Pearson 为 0.5264/0.3370，Spearman 为
0.5655/0.3759，条件方差为 0.00757/0.01121，V2 low-rain/high-water 比例升至 0.4567%。
空间 residual 图也保留 H/B 形成的结构。该结论是 information gain 结论，不自动等同于路线收益。

## 5. Perfect-water-v2 是否有 route value

它会改变决策：与 C00 rain-only 配对的 576 条路线中有 334 条换路；44 条 exposure 更低，242
条相同，290 条更高。总体 S6−rain bootstrap 差为 +0.006776，95% CI
[+0.006468,+0.007098]。因此存在 route influence，但“perfect-water-v2 总体改善路线”未获支持。

## 6. Clean multisource 是否有收益

未获支持。C00 中 rain-only、V2 naive、S5 分别为 0.430471、0.433417、0.433278；S5 仍比
rain-only 高 0.002807。正式全条件 S5−rain 为 +0.000958，95% CI
[+0.000841,+0.001092]。结果已完整保留，没有为使多源获胜而再次调参。

## 7. Stale water 时怎样

C03 中 water 平均有效权重从 clean 的 0.477018 降到 0.007193；S5 exposure 为 0.430508，
接近 rain-only 0.430471，并优于 naive 0.433366。仍保留 2 个 stale-source-induced bad route。

## 8. Missing water 时怎样

C04 的 water 有效权重精确为 0，S5 与 rain-only exposure 都为 0.430471，路线/暴露 fallback
gap 为 0；没有 `missing_source_failed_to_fallback` failure。

## 9. Noisy/degraded water 时怎样

C02 中 water 权重降至 0.035900；S5 exposure 0.430845，比 naive 0.433364 更接近 rain-only
0.430471。机制减小了坏源影响，但不保证每一个配对都更优。

## 10. Rain stale / water fresh 时怎样

C05 中 rain 权重为 0.367879，water 权重为 0.444969，系统相对提高了新鲜 water 的贡献。
S5 exposure 0.439971，优于 naive 0.441619，但仍高于该条件的 rain-only 0.438639。

## 11. Source-specific freshness 是否有效

机制方向有效：water stale 时 source-specific tau 将 water 权重压到 0.007193，而 universal tau
仍为 0.063109。总体 S5−S4 为 −0.000099，95% CI [−0.000206,+0.000002]，区间触及 0，
因此不能声称总体优势已明确成立；各 family 的方向也并不完全一致。

## 12. Reliability-aware fusion 是否有效

相对 V2 naive 有明确的稳健性收益：reliability−naive 为 −0.001918，95% CI
[−0.002084,−0.001748]。它降低了 stale、missing、degraded 和 disagreement 源的影响；这不表示
它总体优于 rain-only。

## 13. Fallback 是否有效

有效。water 不可用而 rain 可用时精确回到 rain-only；若全部动态源都不可用，融合实现退化为
static-only。missing 不被当作 0，planner 也不接收 latent truth。

## 14. Failure cases

正式保留 462 条失败记录：multisource worse than rain-only 236、unnecessary replan 122、
trusted worse than naive 68、missed useful replan 22、route oscillation 11、stale bad route 2、
bad-source overweighted 1。没有删除失败 seed 或不利场景。

## 15. Trigger

never/always/triggered 的平均 exposure 为 0.437542/0.430985/0.434785，平均 planner calls 为
1.00/12.00/1.77。triggered 在风险与计算量之间形成折中；仍保留 22 个 missed useful、122 个
unnecessary replan 与 11 个 oscillation failure。

## 16. UI 是否能看到所有 source

能。新增“异步多源机制实验”，同时显示受控模拟 rain 与 48 个受控模拟 water sensor，并支持
正常、通信中断和恢复演示。2026-09-25 浏览器自动检查确认页面显示 48/48，sensor payload 数量
为 48；人工交互复核仍保留在 `docs/MULTISOURCE_V2_UI_REVIEW.md`，没有自动勾选。

## 17. UI 是否显示具体 source data

能。sensor popup 显示 sensor_id、`water_level_index`、observation timestamp、`retrieved_at`、
age、quality、availability 与 source type；missing 显示“暂无可靠数据/不可用”。路线结果显示两个
source 的 freshness、effective contribution 与 fallback fraction。浏览器已实际打开 S048 popup
验证这些字段。

## 18. 真实/模拟是否明确区分

是。真实场景继续显示“真实水位数据：未启用”；多源场景反复标明“受控模拟”“不是历史实测”
和“不代表真实道路积水深度”。S6 perfect reference、H、B 与完整 latent truth 不进入 UI。

## 19. Reproducibility

正式实验完整运行两次。`reproducibility.json` 中 12 个稳定输出文件的 SHA-256 全部一致，
`all_stable_outputs_identical=true`；仅 wall-clock timing 被排除。正式输出共 28,224 条路线，其中
27,648 条主方法路线、576 条 perfect reference；Trigger 汇总 378 条。

## 20. Tests

最终环境 `python -m pip check` 无损坏依赖；`python -m unittest discover -s tests -q` 共运行
163 项并全部通过，其中 33 项为 Multisource Fusion V2 测试。浏览器自动检查还确认 48 个 sensor、
popup 完整、切换在线底图前后 `mapInstanceId` 不变且控制台 0 error。起终点、路线及状态联动仍按
要求留给用户人工复核。

## 21. 未获支持的结论

- 不支持 clean V2 multisource 或 perfect-water-v2 总体优于 rain-only；
- 不支持 source-specific tau 存在明确非零的总体优势；
- 不支持 source disagreement 下多源优于 rain-only；
- 不支持所有坏源条件、所有 seed、所有 OD 都没有个别劣化；
- 不支持 Trigger 同时达到 always 的风险和 never 的计算量；
- 不支持将模拟研究结果解释为真实深圳水位验证或现实导航安全证明。

## 22. 现实边界

道路、DEM、WorldCover 与 OSM 几何来自项目既有真实 GIS 数据；rain forcing、H、B、water truth
与 sensor observation 均为受控模拟。本研究没有真实深圳道路水位、真实堵塞点、泵站状态、
排水能力或道路通行验证。`water_level_index` 是 [0,1] 无量纲状态指数，不是厘米水深。研究只支持
“独立信息可被识别、坏源可被降权、缺失源可安全退化”的受控机制结论。

## 交付物与版本保护

- 正式报告：`docs/MULTISOURCE_FUSION_V2_REPORT.md`
- 冻结协议：`docs/MULTISOURCE_FUSION_V2_PROTOCOL.md`
- 结果目录：`results/multisource_fusion_v2/`
- 人工 UI 清单：`docs/MULTISOURCE_V2_UI_REVIEW.md`（全部保持未勾选）
- 第一版结果 `results/multisource_synthetic_water/` 与旧分支/tag 均未修改。
- 未创建 `v1.5.0-multisource-fusion-v2` tag；只有人工复核通过后才可创建。
