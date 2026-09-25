# Multisource V1 机制诊断

## 诊断边界

本阶段只重放已冻结 V1 生成器与算法，没有修改 source weight、tau、uncertainty、routing、truth、sensor layout 或第一版结果。阈值在脚本中固定为 `rain_truth_risk <= 0.25` 与 `latent_water_truth >= 0.5`，未根据结果调整。

## 1. Rain 与 Water 是否高度相关

在 48,478,176 个 edge×time×scenario×seed 观测上，精确 Pearson 为 **0.6219**。按每个 family×seed 分别计算再按样本数汇总的 Spearman 均值为 **0.5655**。这说明 V1 water 与 rain 存在明显相关，但并非完全相同。`water_by_rain_bin.csv` 保留每个固定 rain decile 内的 mean/std/p10/p50/p90。

## 2. Water 是否存在 Rain 无法解释的局部状态

同时控制 rain decile 与 static susceptibility quintile 后，加权平均 conditional water variance 为 **0.007569**。低 rain、高 water 记录共 **17,159** 条，占 **0.0354%**。V1 存在少量条件差异，但其幅度与来源主要仍受 rain 和已知 static susceptibility 驱动，独立现场信息有限。

## 3. Perfect Water 是否改变风险排序与路线

完整比较 576 个 scenario×seed×OD×decision-time 配对。全道路 rain-only 与 perfect-water fusion 风险排序的平均 Spearman 为 **0.9939**。Perfect water 改变路线 **57** 次（9.90%），平均路线 overlap 为 **0.9808**。

配对结果：better 1，equal 519，worse 56；平均 perfect−rain truth exposure 为 **+0.000395**。只看真正换路的配对，平均差为 **+0.003988**。

## 4. 代表案例与 Edge Cost

案例按固定规则选择：全配对中最小差值、绝对差最接近 0、最大差值；不只选择获胜案例。

- **better**：moving_center / seed 8105 / OD08 / step 4，perfect−rain=-0.002408，overlap=0.785。
- **equal**：anisotropic_band / seed 8101 / OD01 / step 4，perfect−rain=+0.000000，overlap=1.000。
- **worse**：anisotropic_band / seed 8101 / OD08 / step 4，perfect−rain=+0.030704，overlap=0.208。

每个案例的 edge CSV 包含 `rain_truth,water_truth,planner_rain_component,planner_water_component,fusion_risk,edge_cost`、两条路线选择标记与风险排名变化。诊断显示 water 确实改变部分 edge 排名，但路径只能沿离散网络选择整段连通道路；局部 ranking 变化常不足以形成更优连通替代，或替代路线在离线 truth objective 上付出其他边的代价。

## 5. 为什么 Perfect Water 没有总体收益

主要问题是组合效应：

1. **source redundancy**：V1 water 主要由 rain 与 planner 已知的静态特征生成；
2. **truth/planner mismatch**：planner 的 source/static 权重与离线 truth 权重不同，perfect observation 不等于 perfect objective；
3. **route discretization**：道路网络的连通替代是离散的，edge risk 排名变化不必然产生可用绕行；
4. **fusion design**：V1 把 uncertainty 与 staleness 主要作为 penalty，active-but-poor source 仍能影响基础风险。

因此当前问题属于上述四项的组合。V2 若要检验第二源价值，必须先加入 rain/static 不能直接推断的空间相关局部状态，再让 freshness、coverage 与 observable quality 控制 source contribution，并显式支持退化到 rain-only/static-only。该结论是新研究设计依据，不改变 V1 的不利结果。
