# FloodRoute 多源模拟积涝研究最终状态

1. **使用什么模拟源？** 使用 `SIMULATED_WATER_SENSOR`，中文名“受控模拟积涝监测源”。
2. **为什么不用真实水位？** 当前没有可重复、字段和时间语义明确且能覆盖本实验条件的深圳真实道路积水时间序列；不能用模拟值冒充真实观测。
3. **模拟 source 是否有物理厘米意义？** 没有。`water_level_index` 是 `[0,1]` 无量纲状态指数。
4. **water truth 如何生成？** 真实静态 GIS 特征形成固定 susceptibility；模拟降雨经 5 分钟积分、道路相关排水时间尺度形成累积和衰减的 latent ponding truth。
5. **sensor 如何布设？** 固定 seed 7401，在 EPSG:32650 的 4×4 空间层内按 low/medium/high susceptibility 各取一条机动车边，共 48 个。
6. **rain cadence？** 15 分钟。
7. **water cadence？** 10 分钟，三组 offset 为 0、3、6 分钟。
8. **tau_rain？** 60 分钟，继承冻结配置。
9. **tau_water？** 20 分钟，复用冻结配置中 dormant water tau；统一 tau 消融为 60 分钟。
10. **delay？** 主实验固定组合覆盖 0、10、30、60 分钟。
11. **missing？** 固定组合覆盖 0、0.2、0.5；另有 block outage 和恢复压力事件。
12. **noise？** 固定组合覆盖 sigma 0、0.05、0.15。
13. **scenario families？** `moving_center`、`dual_center`、`anisotropic_band`。
14. **seeds？** 主实验 8101–8112；Trigger 使用 8101、8106、8112；传感器选择 7401；bootstrap 8301。
15. **OD？** 原扩展验证冻结的 8 组 OD，未按多源结果重新选择。
16. **路线总数？** 28,224：六方法配对路线 27,648，perfect-water 上界参考 576。Trigger 另有 4,536 条逐时策略记录和 378 条事件汇总。
17. **完整方法比较？** `rain_risk` 平均 truth exposure 最低（0.420254）；其后依次为 perfect reference 0.420649、naive 0.423853、uncertainty 0.425196、source-specific 0.425511、universal 0.425578；shortest 为 0.446172。
18. **source-specific tau 是否有效？** 相对 universal tau 有极小改善：均值差 −0.000068，seed-level 95% bootstrap CI [−0.000108, −0.000033]；但没有优于 rain-only。
19. **uncertainty 是否有效？** 未得到支持。相对 naive 的均值差为 +0.001343，95% CI [+0.001190, +0.001493]。
20. **trusted 是否有效？** 未得到总体支持。source-specific trusted 相对 rain-only 的均值差为 +0.005256，95% CI [+0.004805, +0.005646]。
21. **Trigger 是否改善？** 它减少计算：triggered 平均调用 1.849 次，always 12 次；但平均 exposure 0.433071，高于 always 的 0.429953，因此仍是风险与计算的折中。
22. **所有 failure cases？** 共 924 条：multisource worse than rain-only 496、trusted worse than naive 279、unnecessary replan 85、route oscillation 36、missed useful replan 22、stale-source-induced bad route 6。全部保留。
23. **reproducibility？** 通过。完整实验独立运行两次；剔除 wall-clock timing 后，11 个科学输出文件的逐文件 hash 全部一致，详见 `results/multisource_synthetic_water/reproducibility.json`。
24. **tests？** 新增 20 项机制与边界测试；完整测试共 130 项，全部通过。`python -m pip check` 返回 `No broken requirements found.`。
25. **研究边界？** 这是 controlled multi-source mechanism validation。它不是深圳真实水位实验、真实积水深度预测、历史水位重建、水动力模型或现实应急导航安全证明。生产与历史配置继续 `water.active=false`。

详细方法、统计结果和未获支持结论见 `docs/MULTISOURCE_SYNTHETIC_WATER_REPORT.md`。本分支在人工复核前不合并到 `main`。
