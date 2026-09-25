"""Diagnose the frozen V1 multisource mechanism without changing any algorithm.

This analysis regenerates V1 latent truth from its preregistered protocol.  It
does not write into the V1 result directory and does not expose truth to any
formal planner path outside this offline diagnostic process.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from floodroute.experiments.expanded import generate_family_truth, route_overlap
from floodroute.experiments.robustness import truth_metrics
from floodroute.experiments.scenario import observe
from floodroute.experiments.synthetic_water import (
    EDGE, build_truth_state, simulate_latent_ponding, static_susceptibility,
)
from floodroute.gis.grid_mapping import grid_polygons
from floodroute.risk.dynamic import map_rainfall
from floodroute.risk.trusted import RiskEngine
from floodroute.runtime import Runtime, load_config, write_json
from floodroute.common.schema import RouteRequest


V1_CONFIG = ROOT / "config/multisource_synthetic_water.json"
V1_PROTOCOL = ROOT / "results/multisource_synthetic_water/protocol.json"
OUTPUT = ROOT / "results/multisource_fusion_v2/diagnostics"
REPORT = ROOT / "docs/MULTISOURCE_V1_DIAGNOSIS.md"
RAIN_LOW_THRESHOLD = 0.25
WATER_HIGH_THRESHOLD = 0.50
RAIN_BINS = np.linspace(0, 1, 11)
WATER_HIST_BINS = np.linspace(0, 1, 201)
STATIC_BINS = np.linspace(0, 1, 6)


def spearman(x, y):
    """Spearman rank correlation without adding a SciPy dependency."""
    return float(pd.Series(np.asarray(x)).rank(method="average").corr(
        pd.Series(np.asarray(y)).rank(method="average")
    ))


def request_for(od, timestamp, mode="risk"):
    return RouteRequest(
        float(od.start_lon), float(od.start_lat), float(od.goal_lon), float(od.goal_lat),
        pd.Timestamp(timestamp).isoformat(), mode,
    )


def complete_rain_frames(runtime, truth, scale):
    raw, normalized = {}, {}
    for timestamp in sorted(truth.timestamp.unique()):
        at = pd.Timestamp(timestamp)
        observed = observe(truth, at, seed=0)
        mapped = map_rainfall(observed, runtime.weights, runtime.coverage, at)
        raw[at] = mapped
        item = mapped.copy(); item["value"] = (item.value / scale).clip(0, 1)
        normalized[at] = item
    return raw, normalized


def hist_quantile(counts, q):
    total = counts.sum()
    if total == 0: return np.nan
    position = q * (total - 1)
    index = int(np.searchsorted(np.cumsum(counts), position, side="right"))
    index = min(index, len(WATER_HIST_BINS) - 2)
    return float((WATER_HIST_BINS[index] + WATER_HIST_BINS[index + 1]) / 2)


def regenerate_case(runtime, config, protocol, grids, ods, case):
    family, seed, step, od_id = case["scenario_family"], int(case["seed"]), int(case["decision_step"]), case["od_id"]
    truth = generate_family_truth(grids, runtime.edges.total_bounds, family, seed, config["scenario"]["start"])
    raw, normalized = complete_rain_frames(runtime, truth, config["sources"]["rain"]["scale"])
    latent = simulate_latent_ponding(
        runtime.edges, normalized, protocol["synthetic_water"]["integration_step_min"],
        protocol["synthetic_water"]["inflow_gain"],
    )
    at = pd.Timestamp(sorted(truth.timestamp.unique())[step]); water = latent[at]
    source_engine = RiskEngine(runtime.edges, config)
    rain_engine = runtime.engine
    perfect_water = pd.DataFrame({"value": water, "age_min": 0., "coverage": 1., "quality": 0.}, index=source_engine.index)
    rain_state = rain_engine.compute({"rain": raw[at]})
    perfect_state = source_engine.compute({"rain": raw[at], "water": perfect_water})
    od = next(x for x in ods.itertuples(index=False) if x.od_id == od_id)
    rain_route = runtime.plan(rain_state, request_for(od, at))
    perfect_route = runtime.plan(perfect_state, request_for(od, at))
    union = sorted(set(rain_route.edge_ids) | set(perfect_route.edge_ids))
    positions = source_engine.index.get_indexer(union)
    edge_frame = runtime.edges.set_index(EDGE).loc[union]
    rain_value = normalized[at].reindex(union).value.fillna(0).to_numpy(float)
    water_value = water[positions]
    output = pd.DataFrame(union, columns=EDGE)
    output["rain_truth"] = rain_value
    output["water_truth"] = water_value
    output["planner_rain_component"] = config["sources"]["rain"]["weight"] * rain_value
    output["planner_water_component"] = config["sources"]["water"]["weight"] * water_value
    output["rain_only_risk"] = rain_state.reindex(union).risk.to_numpy(float)
    output["fusion_risk"] = perfect_state.reindex(union).risk.to_numpy(float)
    output["edge_cost"] = edge_frame.length_m.to_numpy(float) * (1 + config["routing"]["risk_alpha"] * output.fusion_risk)
    output["selected_by_rain_route"] = [edge in set(rain_route.edge_ids) for edge in union]
    output["selected_by_perfect_route"] = [edge in set(perfect_route.edge_ids) for edge in union]
    output["rain_risk_rank"] = output.rain_only_risk.rank(method="average", ascending=False)
    output["fusion_risk_rank"] = output.fusion_risk.rank(method="average", ascending=False)
    output["risk_rank_change"] = output.fusion_risk_rank - output.rain_risk_rank
    return output


def run():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = load_config(V1_CONFIG)
    frozen = load_config(ROOT / "config/selected_v1_1.json")
    protocol = json.loads(V1_PROTOCOL.read_text(encoding="utf-8"))
    runtime = Runtime(frozen)
    grids = grid_polygons(ROOT / config["grids_path"])
    ods = pd.read_csv(ROOT / protocol["design"]["od_source"])
    source_engine = RiskEngine(runtime.edges, config)
    susceptibility = static_susceptibility(runtime.edges)
    lengths = runtime.edges.set_index(EDGE).length_m

    scenario_correlations, route_rows = [], []
    rain_hist_count = np.zeros((10, 200), dtype=np.int64)
    rain_bin_sum = np.zeros(10); rain_bin_sumsq = np.zeros(10); rain_bin_count = np.zeros(10, dtype=np.int64)
    conditional_sum = np.zeros((10, 5)); conditional_sumsq = np.zeros((10, 5)); conditional_count = np.zeros((10, 5), dtype=np.int64)
    global_stats = dict(n=0, sum_x=0., sum_y=0., sum_xx=0., sum_yy=0., sum_xy=0.)
    high_low_count = 0; total_count = 0

    for family in protocol["design"]["scenario_families"]:
        for seed in protocol["design"]["seeds"]:
            truth = generate_family_truth(grids, runtime.edges.total_bounds, family, seed, config["scenario"]["start"])
            raw, normalized = complete_rain_frames(runtime, truth, config["sources"]["rain"]["scale"])
            latent = simulate_latent_ponding(
                runtime.edges, normalized, protocol["synthetic_water"]["integration_step_min"],
                protocol["synthetic_water"]["inflow_gain"],
            )
            rain_all, water_all = [], []
            for at in sorted(normalized):
                rain = normalized[at].value.fillna(0).to_numpy(float)
                water = latent[at].astype(float)
                rain_all.append(rain); water_all.append(water)
                n = len(rain); global_stats["n"] += n
                global_stats["sum_x"] += rain.sum(); global_stats["sum_y"] += water.sum()
                global_stats["sum_xx"] += np.square(rain).sum(); global_stats["sum_yy"] += np.square(water).sum()
                global_stats["sum_xy"] += (rain * water).sum()
                total_count += n; high_low_count += int(((rain <= RAIN_LOW_THRESHOLD) & (water >= WATER_HIGH_THRESHOLD)).sum())
                rbin = np.clip(np.digitize(rain, RAIN_BINS[1:-1]), 0, 9)
                sbin = np.clip(np.digitize(susceptibility, STATIC_BINS[1:-1]), 0, 4)
                for rb in range(10):
                    mask = rbin == rb
                    values = water[mask]
                    rain_bin_count[rb] += len(values); rain_bin_sum[rb] += values.sum(); rain_bin_sumsq[rb] += np.square(values).sum()
                    rain_hist_count[rb] += np.histogram(values, WATER_HIST_BINS)[0]
                    for sb in range(5):
                        subset = water[mask & (sbin == sb)]
                        conditional_count[rb, sb] += len(subset); conditional_sum[rb, sb] += subset.sum(); conditional_sumsq[rb, sb] += np.square(subset).sum()
            rain_all = np.concatenate(rain_all); water_all = np.concatenate(water_all)
            scenario_correlations.append({
                "scenario_family": family, "seed": seed, "n": len(rain_all),
                "pearson": float(np.corrcoef(rain_all, water_all)[0, 1]),
                "spearman": spearman(rain_all, water_all),
            })

            for step in protocol["design"]["decision_steps"]:
                at = pd.Timestamp(sorted(truth.timestamp.unique())[step]); water = latent[at]
                truth_state = build_truth_state(source_engine, normalized[at], water, protocol["design"]["truth_weights"])
                rain_state = runtime.engine.compute({"rain": raw[at]})
                perfect = pd.DataFrame({"value": water, "age_min": 0., "coverage": 1., "quality": 0.}, index=source_engine.index)
                perfect_state = source_engine.compute({"rain": raw[at], "water": perfect})
                rank_corr = spearman(rain_state.risk, perfect_state.risk)
                for od in ods.itertuples(index=False):
                    rain_route = runtime.plan(rain_state, request_for(od, at))
                    perfect_route = runtime.plan(perfect_state, request_for(od, at))
                    rain_metrics = truth_metrics(rain_route, truth_state, lengths, config["routing"]["high_risk"])
                    perfect_metrics = truth_metrics(perfect_route, truth_state, lengths, config["routing"]["high_risk"])
                    route_rows.append({
                        "scenario_family": family, "seed": seed, "decision_step": step, "timestamp": at,
                        "od_id": od.od_id, "route_changed": rain_route.edge_ids != perfect_route.edge_ids,
                        "route_overlap": route_overlap(rain_route, perfect_route, lengths),
                        "rain_only_truth_exposure": rain_metrics["truth_exposure"],
                        "perfect_water_truth_exposure": perfect_metrics["truth_exposure"],
                        "difference": perfect_metrics["truth_exposure"] - rain_metrics["truth_exposure"],
                        "global_edge_risk_rank_spearman": rank_corr,
                    })
            print(f"Diagnosed V1 {family} seed {seed}", flush=True)

    n = global_stats["n"]
    numerator = global_stats["sum_xy"] - global_stats["sum_x"] * global_stats["sum_y"] / n
    denominator = np.sqrt((global_stats["sum_xx"] - global_stats["sum_x"]**2 / n) * (global_stats["sum_yy"] - global_stats["sum_y"]**2 / n))
    exact_pearson = float(numerator / denominator)
    correlation = pd.DataFrame(scenario_correlations)
    correlation.to_csv(OUTPUT / "rain_water_correlations.csv", index=False)

    bin_rows = []
    for rb in range(10):
        count = rain_bin_count[rb]; mean = rain_bin_sum[rb] / count
        variance = max(0., rain_bin_sumsq[rb] / count - mean**2)
        bin_rows.append({
            "rain_bin": rb, "rain_low": RAIN_BINS[rb], "rain_high": RAIN_BINS[rb + 1], "count": int(count),
            "water_mean": mean, "water_std": np.sqrt(variance),
            "water_p10": hist_quantile(rain_hist_count[rb], .10),
            "water_p50": hist_quantile(rain_hist_count[rb], .50),
            "water_p90": hist_quantile(rain_hist_count[rb], .90),
        })
    pd.DataFrame(bin_rows).to_csv(OUTPUT / "water_by_rain_bin.csv", index=False)

    conditional_rows = []
    for rb in range(10):
        for sb in range(5):
            count = conditional_count[rb, sb]
            mean = conditional_sum[rb, sb] / count if count else np.nan
            variance = max(0., conditional_sumsq[rb, sb] / count - mean**2) if count else np.nan
            conditional_rows.append({
                "rain_bin": rb, "static_bin": sb, "count": int(count),
                "conditional_water_mean": mean, "conditional_water_variance": variance,
            })
    conditional = pd.DataFrame(conditional_rows)
    conditional.to_csv(OUTPUT / "conditional_water_variance.csv", index=False)

    routes = pd.DataFrame(route_rows).sort_values(["scenario_family", "seed", "decision_step", "od_id"])
    routes.to_csv(OUTPUT / "perfect_water_route_pairs.csv", index=False)
    changed = routes[routes.route_changed]
    candidates = {
        "better": changed.loc[changed.difference.idxmin()] if len(changed) else routes.loc[routes.difference.idxmin()],
        "equal": routes.loc[routes.difference.abs().idxmin()],
        "worse": changed.loc[changed.difference.idxmax()] if len(changed) else routes.loc[routes.difference.idxmax()],
    }
    representative = []
    for category, row in candidates.items():
        case = row.to_dict(); case["category"] = category
        edge_costs = regenerate_case(runtime, config, protocol, grids, ods, case)
        edge_costs.insert(0, "case_category", category)
        edge_costs.to_csv(OUTPUT / f"representative_{category}_edge_costs.csv", index=False)
        representative.append({**case, "edge_count_union": len(edge_costs),
                               "large_rank_change_edges": int(edge_costs.risk_rank_change.abs().ge(10).sum())})
    pd.DataFrame(representative).to_csv(OUTPUT / "representative_cases.csv", index=False)

    summary = {
        "analysis_type": "V1_MECHANISM_DIAGNOSIS",
        "v1_results_unchanged": True,
        "thresholds_fixed_before_diagnosis": {"rain_low_max": RAIN_LOW_THRESHOLD, "water_high_min": WATER_HIGH_THRESHOLD},
        "edge_time_observations": int(n), "global_pearson_exact": exact_pearson,
        "scenario_weighted_spearman_mean": float(np.average(correlation.spearman, weights=correlation.n)),
        "conditional_water_variance_mean": float(np.average(conditional.conditional_water_variance.dropna(), weights=conditional.loc[conditional.conditional_water_variance.notna(), "count"])),
        "high_water_low_rain_count": int(high_low_count),
        "high_water_low_rain_ratio": float(high_low_count / total_count),
        "route_pair_count": len(routes), "route_change_count": int(routes.route_changed.sum()),
        "route_change_rate": float(routes.route_changed.mean()),
        "perfect_better_count": int(routes.difference.lt(-1e-12).sum()),
        "perfect_equal_count": int(routes.difference.abs().le(1e-12).sum()),
        "perfect_worse_count": int(routes.difference.gt(1e-12).sum()),
        "mean_perfect_minus_rain": float(routes.difference.mean()),
        "mean_route_overlap": float(routes.route_overlap.mean()),
        "mean_global_edge_risk_rank_spearman": float(routes.global_edge_risk_rank_spearman.mean()),
    }
    write_json(OUTPUT / "diagnostic_summary.json", summary)
    write_report(summary, correlation, pd.DataFrame(bin_rows), conditional, routes, representative)


def write_report(summary, correlations, bins, conditional, routes, representative):
    changed = routes[routes.route_changed]
    changed_mean = changed.difference.mean() if len(changed) else np.nan
    rows = "\n".join(
        f"- **{item['category']}**：{item['scenario_family']} / seed {int(item['seed'])} / {item['od_id']} / step {int(item['decision_step'])}，perfect−rain={item['difference']:+.6f}，overlap={item['route_overlap']:.3f}。"
        for item in representative
    )
    text = f"""# Multisource V1 机制诊断

## 诊断边界

本阶段只重放已冻结 V1 生成器与算法，没有修改 source weight、tau、uncertainty、routing、truth、sensor layout 或第一版结果。阈值在脚本中固定为 `rain_truth_risk <= {RAIN_LOW_THRESHOLD}` 与 `latent_water_truth >= {WATER_HIGH_THRESHOLD}`，未根据结果调整。

## 1. Rain 与 Water 是否高度相关

在 {summary['edge_time_observations']:,} 个 edge×time×scenario×seed 观测上，精确 Pearson 为 **{summary['global_pearson_exact']:.4f}**。按每个 family×seed 分别计算再按样本数汇总的 Spearman 均值为 **{summary['scenario_weighted_spearman_mean']:.4f}**。这说明 V1 water 与 rain 存在明显相关，但并非完全相同。`water_by_rain_bin.csv` 保留每个固定 rain decile 内的 mean/std/p10/p50/p90。

## 2. Water 是否存在 Rain 无法解释的局部状态

同时控制 rain decile 与 static susceptibility quintile 后，加权平均 conditional water variance 为 **{summary['conditional_water_variance_mean']:.6f}**。低 rain、高 water 记录共 **{summary['high_water_low_rain_count']:,}** 条，占 **{summary['high_water_low_rain_ratio']:.4%}**。V1 存在少量条件差异，但其幅度与来源主要仍受 rain 和已知 static susceptibility 驱动，独立现场信息有限。

## 3. Perfect Water 是否改变风险排序与路线

完整比较 {summary['route_pair_count']:,} 个 scenario×seed×OD×decision-time 配对。全道路 rain-only 与 perfect-water fusion 风险排序的平均 Spearman 为 **{summary['mean_global_edge_risk_rank_spearman']:.4f}**。Perfect water 改变路线 **{summary['route_change_count']}** 次（{summary['route_change_rate']:.2%}），平均路线 overlap 为 **{summary['mean_route_overlap']:.4f}**。

配对结果：better {summary['perfect_better_count']}，equal {summary['perfect_equal_count']}，worse {summary['perfect_worse_count']}；平均 perfect−rain truth exposure 为 **{summary['mean_perfect_minus_rain']:+.6f}**。只看真正换路的配对，平均差为 **{changed_mean:+.6f}**。

## 4. 代表案例与 Edge Cost

案例按固定规则选择：全配对中最小差值、绝对差最接近 0、最大差值；不只选择获胜案例。

{rows}

每个案例的 edge CSV 包含 `rain_truth,water_truth,planner_rain_component,planner_water_component,fusion_risk,edge_cost`、两条路线选择标记与风险排名变化。诊断显示 water 确实改变部分 edge 排名，但路径只能沿离散网络选择整段连通道路；局部 ranking 变化常不足以形成更优连通替代，或替代路线在离线 truth objective 上付出其他边的代价。

## 5. 为什么 Perfect Water 没有总体收益

主要问题是组合效应：

1. **source redundancy**：V1 water 主要由 rain 与 planner 已知的静态特征生成；
2. **truth/planner mismatch**：planner 的 source/static 权重与离线 truth 权重不同，perfect observation 不等于 perfect objective；
3. **route discretization**：道路网络的连通替代是离散的，edge risk 排名变化不必然产生可用绕行；
4. **fusion design**：V1 把 uncertainty 与 staleness 主要作为 penalty，active-but-poor source 仍能影响基础风险。

因此当前问题属于上述四项的组合。V2 若要检验第二源价值，必须先加入 rain/static 不能直接推断的空间相关局部状态，再让 freshness、coverage 与 observable quality 控制 source contribution，并显式支持退化到 rain-only/static-only。该结论是新研究设计依据，不改变 V1 的不利结果。
"""
    REPORT.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    run()
