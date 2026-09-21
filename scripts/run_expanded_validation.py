"""Execute the committed frozen Phase C validation protocol."""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import hashlib
import itertools
import json
from pathlib import Path
import sys
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from floodroute.common.schema import RouteRequest
from floodroute.experiments.expanded import (
    FAMILIES, generate_family_truth, observation_digest, route_digest,
    route_overlap, select_od_pairs, stable_seed,
)
from floodroute.experiments.replay import ReplayController
from floodroute.experiments.robustness import truth_metrics
from floodroute.experiments.scenario import observe
from floodroute.gis.grid_mapping import grid_polygons
from floodroute.risk.dynamic import map_rainfall
from floodroute.runtime import Runtime, write_json


CONFIG_PATH = ROOT / "config/selected_v1_1.json"
PROTOCOL_PATH = ROOT / "results/expanded_validation/protocol.json"
EXPECTED_CONFIG_SHA256 = "3f8ea08239d12d19b801afec28b5156625dd08daef4f54ff72573756bd7e6dd5"
METHODS = ("shortest", "risk", "risk_uncertainty", "trusted")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request_for(od, timestamp, mode):
    return RouteRequest(
        float(od.start_lon), float(od.start_lat), float(od.goal_lon), float(od.goal_lat),
        pd.Timestamp(timestamp).isoformat(), mode,
    )


def evaluate_routes(runtime, grids, protocol, ods):
    lengths = runtime.edges.set_index(["u", "v", "key"]).length_m
    conditions = list(itertools.product(protocol["delays_min"], protocol["missing_rates"], protocol["noise_levels"]))
    decision_by_step = {x["step_index"]: x["phase"] for x in protocol["decision_times"]}
    shortest_cache = {}
    rows = []; scenario_rows = []
    bounds = runtime.edges.total_bounds
    for family in protocol["scenario_families"]:
        for seed in protocol["seeds"]:
            truth = generate_family_truth(grids, bounds, family, seed, protocol["scenario_start"])
            scenario_rows.append({
                "scenario_family": family, "seed": seed, "steps": int(truth.timestamp.nunique()),
                "start": pd.Timestamp(truth.timestamp.min()).isoformat(),
                "end": pd.Timestamp(truth.timestamp.max()).isoformat(),
                "rain_min_mm": float(truth.rain_mm.min()), "rain_max_mm": float(truth.rain_mm.max()),
                "rain_mean_mm": float(truth.rain_mm.mean()),
                "grid_count": int(truth.grid_id.nunique()), "data_type": "SIMULATED_EXPANDED_VALIDATION",
                "truth_use": "offline evaluation and observation generation only",
            })
            times = sorted(truth.timestamp.unique())
            for step, phase in decision_by_step.items():
                at = pd.Timestamp(times[step])
                perfect = observe(truth, at, seed=stable_seed(family, seed, step, "truth"))
                truth_state = runtime.observed_state(perfect, at)
                for delay, missing, noise in conditions:
                    obs_seed = stable_seed(family, seed, step, delay, missing, noise, "observation")
                    observed = observe(truth, at, delay, missing, noise, obs_seed)
                    digest = observation_digest(observed)
                    begin = time.perf_counter()
                    mapped = map_rainfall(observed, runtime.weights, runtime.coverage, at)
                    mapping_ms = (time.perf_counter() - begin) * 1000
                    begin = time.perf_counter(); state = runtime.engine.compute({"rain": mapped})
                    state_ms = (time.perf_counter() - begin) * 1000
                    for od in ods.itertuples(index=False):
                        cache_key = od.od_id
                        if cache_key not in shortest_cache:
                            begin = time.perf_counter()
                            shortest_cache[cache_key] = runtime.plan(state, request_for(od, at, "shortest"))
                            shortest_cache[cache_key + "_ms"] = (time.perf_counter() - begin) * 1000
                        shortest = shortest_cache[cache_key]
                        order = np.random.default_rng(stable_seed(obs_seed, od.od_id, "method_order")).permutation(METHODS)
                        for method in order:
                            if method == "shortest":
                                route = shortest; planning_ms = float(shortest_cache[cache_key + "_ms"])
                            else:
                                begin = time.perf_counter()
                                route = runtime.plan(state, request_for(od, at, str(method)))
                                planning_ms = (time.perf_counter() - begin) * 1000
                            metrics = truth_metrics(route, truth_state, lengths, runtime.config["routing"]["high_risk"])
                            rows.append({
                                "scenario_family": family, "seed": seed, "od_id": od.od_id,
                                "decision_phase": phase, "decision_step": step, "timestamp": at,
                                "delay_min": delay, "missing_rate": missing, "noise": noise,
                                "observation_seed": obs_seed, "observation_digest": digest,
                                "method": str(method), **metrics,
                                "route_overlap_with_shortest": route_overlap(route, shortest, lengths),
                                "mapping_ms": mapping_ms, "state_ms": state_ms, "planning_ms": planning_ms,
                                "computation_ms": mapping_ms + state_ms + planning_ms,
                                "route_digest": route_digest(route.edge_ids), "route_edge_count": len(route.edge_ids),
                            })
            print(f"Expanded routes complete: {family} seed {seed} ({len(rows):,} rows)", flush=True)
    routes = pd.DataFrame(rows)
    expected = int(protocol["planned_route_decisions"])
    if len(routes) != expected:
        raise AssertionError(f"Expected {expected:,} routes, got {len(routes):,}")
    pairing = routes.groupby([
        "scenario_family", "seed", "od_id", "decision_phase", "delay_min", "missing_rate", "noise"
    ])["observation_digest"].nunique()
    if not pairing.eq(1).all():
        raise AssertionError("Methods did not share paired observations")
    baseline_keys = ["scenario_family", "seed", "od_id", "decision_phase", "method"]
    baseline = routes[
        routes.delay_min.eq(0) & routes.missing_rate.eq(0) & routes.noise.eq(0)
    ].set_index(baseline_keys).route_digest
    routes["route_change_from_baseline"] = [
        digest != baseline.loc[(family, seed, od_id, phase, method)]
        for family, seed, od_id, phase, method, digest in routes[
            baseline_keys + ["route_digest"]
        ].itertuples(index=False, name=None)
    ]
    return routes.sort_values([
        "scenario_family", "seed", "od_id", "decision_step", "delay_min", "missing_rate", "noise", "method"
    ]).reset_index(drop=True), pd.DataFrame(scenario_rows)


def summarize_routes(routes, protocol):
    metrics = ["truth_exposure", "distance_m", "max_truth_risk", "p95_truth_risk", "high_risk_length_ratio", "route_overlap_with_shortest", "route_change_from_baseline", "computation_ms"]
    seed_summary = routes.groupby(["scenario_family", "seed", "method"], as_index=False)[metrics].mean()
    family_summary = seed_summary.groupby(["scenario_family", "method"], as_index=False).agg(
        n_seeds=("seed", "nunique"), mean_truth_exposure=("truth_exposure", "mean"),
        seed_sd_truth_exposure=("truth_exposure", "std"), mean_distance_m=("distance_m", "mean"),
        mean_high_risk_length_ratio=("high_risk_length_ratio", "mean"),
        mean_route_overlap_with_shortest=("route_overlap_with_shortest", "mean"),
        route_change_rate=("route_change_from_baseline", "mean"), mean_computation_ms=("computation_ms", "mean"),
    )
    comparison_specs = [
        ("risk-shortest", "risk", "shortest"),
        ("risk_uncertainty-risk", "risk_uncertainty", "risk"),
        ("trusted-risk", "trusted", "risk"),
        ("trusted-risk_uncertainty", "trusted", "risk_uncertainty"),
    ]
    wide = seed_summary.pivot(index=["scenario_family", "seed"], columns="method", values="truth_exposure")
    comparison_rows = []
    for (family, seed), row in wide.iterrows():
        for name, left, right in comparison_specs:
            comparison_rows.append({"scenario_family": family, "seed": seed, "comparison": name, "mean_difference": float(row[left] - row[right])})
    comparisons = pd.DataFrame(comparison_rows)
    bootstrap_rows = []
    rng = np.random.default_rng(protocol["bootstrap"]["seed"])
    seeds = np.array(protocol["seeds"])
    for family in [*protocol["scenario_families"], "all_families"]:
        subset = comparisons if family == "all_families" else comparisons[comparisons.scenario_family.eq(family)]
        for name, group in subset.groupby("comparison"):
            by_seed = group.groupby("seed").mean_difference.mean().reindex(seeds)
            samples = np.empty(protocol["bootstrap"]["iterations"])
            for i in range(len(samples)):
                picked = rng.choice(seeds, size=len(seeds), replace=True)
                samples[i] = by_seed.loc[picked].mean()
            bootstrap_rows.append({
                "scenario_family": family, "comparison": name,
                "mean_difference": float(by_seed.mean()),
                "ci_low": float(np.quantile(samples, .025)), "ci_high": float(np.quantile(samples, .975)),
                "bootstrap_unit": "seed", "iterations": int(len(samples)), "bootstrap_seed": protocol["bootstrap"]["seed"],
            })
    return seed_summary, family_summary, comparisons, pd.DataFrame(bootstrap_rows)


def run_trigger_stress(runtime, grids, protocol, ods):
    lengths = runtime.edges.set_index(["u", "v", "key"]).length_m
    bounds = runtime.edges.total_bounds
    event_rows = []; detailed = []
    chosen_ods = ods[ods.od_id.isin(protocol["trigger_replay"]["od_ids"])]
    for family in protocol["trigger_replay"]["families"]:
        for seed in protocol["trigger_replay"]["seeds"]:
            truth = generate_family_truth(grids, bounds, family, seed, protocol["scenario_start"])
            for od in chosen_ods.itertuples(index=False):
                controllers = {name: ReplayController(runtime, name) for name in protocol["trigger_replay"]["policies"]}
                per_policy = {name: [] for name in controllers}
                for step, at in enumerate(sorted(truth.timestamp.unique())):
                    at = pd.Timestamp(at)
                    observed = observe(
                        truth, at, protocol["trigger_replay"]["delay_min"],
                        protocol["trigger_replay"]["missing_rate"], protocol["trigger_replay"]["noise"],
                        stable_seed(family, seed, od.od_id, step, "trigger_observation"),
                    )
                    begin = time.perf_counter(); state = runtime.observed_state(observed, at)
                    state_ms = (time.perf_counter() - begin) * 1000
                    truth_state = runtime.observed_state(observe(truth, at, seed=stable_seed(family, seed, step, "trigger_truth")), at)
                    for policy, controller in controllers.items():
                        begin = time.perf_counter()
                        log = controller.step(state, request_for(od, at, "trusted"))
                        elapsed = (time.perf_counter() - begin) * 1000
                        metrics = truth_metrics(controller.current_route, truth_state, lengths, runtime.config["routing"]["high_risk"])
                        record = {
                            "scenario_family": family, "seed": seed, "od_id": od.od_id, "step": step,
                            "timestamp": at, "policy": policy, **log, **metrics,
                            "computation_ms": state_ms + elapsed,
                            "route_digest": route_digest(controller.current_route.edge_ids),
                        }
                        detailed.append(record); per_policy[policy].append(record)
                summary_by_policy = {}
                for policy, records in per_policy.items():
                    frame = pd.DataFrame(records)
                    summary_by_policy[policy] = {
                        "mean_truth_exposure": float(frame.truth_exposure.mean()),
                        "final_replan_count": int(frame.replan_count.iloc[-1]),
                        "final_route_change_count": int(frame.route_change_count.iloc[-1]),
                        "planner_calls": int(frame.planner_calls.iloc[-1]),
                        "total_computation_ms": float(frame.computation_ms.sum()),
                    }
                triggered = summary_by_policy["triggered"]; always = summary_by_policy["always"]
                flags = {
                    "missed_useful_replan": triggered["mean_truth_exposure"] > always["mean_truth_exposure"] + .01,
                    "frequent_search": triggered["final_replan_count"] >= 8,
                    "oscillation": triggered["final_route_change_count"] >= 4,
                }
                for policy, values in summary_by_policy.items():
                    event_rows.append({
                        "scenario_family": family, "seed": seed, "od_id": od.od_id, "policy": policy,
                        **values, **(flags if policy == "triggered" else {key: False for key in flags}),
                    })
            print(f"Trigger stress complete: {family} seed {seed}", flush=True)
    return pd.DataFrame(event_rows), pd.DataFrame(detailed)


def configure_chinese_font():
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def plot_results(output, routes, family_summary, bootstrap, trigger_summary):
    configure_chinese_font(); figures = output / "figures"; figures.mkdir(parents=True, exist_ok=True)
    methods = list(METHODS); labels = ["最短路径", "风险优先", "风险＋不确定性", "可信优先"]
    colors = ["#777777", "#d95f02", "#7570b3", "#1b9e77"]

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8), sharey=True)
    for ax, family in zip(axes, FAMILIES):
        part = family_summary[family_summary.scenario_family.eq(family)].set_index("method").reindex(methods)
        ax.bar(labels, part.mean_truth_exposure, yerr=part.seed_sd_truth_exposure, color=colors, capsize=3)
        ax.set_title({"moving_center":"移动中心", "dual_center":"双中心", "anisotropic_band":"带状雨带"}[family])
        ax.tick_params(axis="x", rotation=25); ax.grid(axis="y", alpha=.2)
    axes[0].set_ylabel("长度加权真实风险暴露")
    fig.suptitle("不同场景家族的风险暴露对比（误差线：种子间标准差）")
    fig.tight_layout(); fig.savefig(figures / "不同场景家族的风险暴露对比.png", dpi=180); plt.close(fig)

    overall = bootstrap[bootstrap.scenario_family.eq("all_families")]
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(overall)); means = overall.mean_difference.to_numpy();
    err = np.vstack([means - overall.ci_low.to_numpy(), overall.ci_high.to_numpy() - means])
    ax.errorbar(x, means, yerr=err, fmt="o", capsize=5, color="#2c7fb8")
    ax.axhline(0, color="black", linewidth=1); ax.set_xticks(x, overall.comparison, rotation=20)
    ax.set_ylabel("前者减后者的真实风险暴露"); ax.set_title("冻结参数扩展测试方法对比（种子级 bootstrap 95% 置信区间）"); ax.grid(alpha=.2)
    fig.tight_layout(); fig.savefig(figures / "冻结参数扩展测试方法对比.png", dpi=180); plt.close(fig)

    for column, filename, title, xlabel in [
        ("delay_min", "观测延迟鲁棒性扩展验证.png", "观测延迟鲁棒性扩展验证", "观测延迟（分钟）"),
        ("missing_rate", "数据缺失鲁棒性扩展验证.png", "数据缺失鲁棒性扩展验证", "数据缺失率"),
    ]:
        seed_means = routes.groupby(["seed", "method", column], as_index=False).truth_exposure.mean()
        stats = seed_means.groupby(["method", column]).truth_exposure.agg(["mean", "std"]).reset_index()
        fig, ax = plt.subplots(figsize=(9, 5))
        for method, label, color in zip(methods, labels, colors):
            part = stats[stats.method.eq(method)]
            ax.errorbar(part[column], part["mean"], yerr=part["std"], marker="o", capsize=3, label=label, color=color)
        ax.set(title=title + "（误差线：种子间标准差）", xlabel=xlabel, ylabel="长度加权真实风险暴露")
        ax.legend(); ax.grid(alpha=.2); fig.tight_layout(); fig.savefig(figures / filename, dpi=180); plt.close(fig)

    od = routes.groupby(["od_id", "method"], as_index=False).truth_exposure.mean()
    fig, ax = plt.subplots(figsize=(11, 5))
    width = .2; xs = np.arange(od.od_id.nunique())
    for i, (method, label, color) in enumerate(zip(methods, labels, colors)):
        part = od[od.method.eq(method)].set_index("od_id").reindex(sorted(od.od_id.unique()))
        ax.bar(xs + (i - 1.5) * width, part.truth_exposure, width, label=label, color=color)
    ax.set_xticks(xs, sorted(od.od_id.unique())); ax.set(title="不同起终点下的方法差异", xlabel="固定 OD", ylabel="长度加权真实风险暴露")
    ax.legend(); ax.grid(axis="y", alpha=.2); fig.tight_layout(); fig.savefig(figures / "不同起终点下的方法差异.png", dpi=180); plt.close(fig)

    trig = trigger_summary.groupby("policy", as_index=False).agg(
        mean_truth_exposure=("mean_truth_exposure", "mean"), seed_sd=("mean_truth_exposure", "std"),
        mean_replans=("final_replan_count", "mean"), mean_changes=("final_route_change_count", "mean"),
    ).set_index("policy").reindex(["never", "always", "triggered"])
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    axes[0].bar(["不重规划", "每次重规划", "触发式"], trig.mean_truth_exposure, yerr=trig.seed_sd, capsize=3, color=colors[:3])
    axes[0].set_title("平均真实风险暴露（误差线：事件间标准差）")
    axes[1].bar(np.arange(3)-.16, trig.mean_replans, .32, label="平均重规划次数")
    axes[1].bar(np.arange(3)+.16, trig.mean_changes, .32, label="平均换路次数")
    axes[1].set_xticks(np.arange(3), ["不重规划", "每次重规划", "触发式"]); axes[1].legend(); axes[1].set_title("搜索与换路")
    fig.suptitle("触发式重规划扩展验证"); fig.tight_layout(); fig.savefig(figures / "触发式重规划扩展验证.png", dpi=180); plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results/expanded_validation")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args(); output = args.output; output.mkdir(parents=True, exist_ok=True)
    if file_sha256(CONFIG_PATH) != EXPECTED_CONFIG_SHA256:
        raise ValueError("Frozen selected_v1_1.json hash changed")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    if protocol["config_sha256"] != EXPECTED_CONFIG_SHA256:
        raise ValueError("Protocol/config hash mismatch")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config["sources"]["water"]["active"]:
        raise ValueError("Protocol requires water.active=false")
    runtime = Runtime(config); grids = grid_polygons(ROOT / config["grids_path"])
    ods = select_od_pairs(runtime, protocol["od"]["count"], protocol["od"]["selection_seed"])
    ods.to_csv(output / "od_pairs.csv", index=False)
    routes, scenarios = evaluate_routes(runtime, grids, protocol, ods)
    routes.to_parquet(output / "routes.parquet", index=False, compression="zstd")
    scenarios.to_csv(output / "scenario_manifest.csv", index=False)
    seed_summary, family_summary, comparisons, bootstrap = summarize_routes(routes, protocol)
    seed_summary.to_csv(output / "seed_summary.csv", index=False)
    family_summary.to_csv(output / "family_summary.csv", index=False)
    comparisons.to_csv(output / "method_comparisons.csv", index=False)
    bootstrap.to_csv(output / "bootstrap_ci.csv", index=False)
    trigger_summary, trigger_details = run_trigger_stress(runtime, grids, protocol, ods)
    trigger_summary.to_csv(output / "trigger_summary.csv", index=False)
    trigger_details.to_parquet(output / "trigger_replays.parquet", index=False, compression="zstd")
    (output / "config_snapshot.json").write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (output / "config_sha256.txt").write_text(EXPECTED_CONFIG_SHA256 + "\n", encoding="ascii")
    # Keep protocol output exact even when a separate repeat directory is used.
    (output / "protocol.json").write_text(PROTOCOL_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    run_manifest = {
        "status": "complete", "route_decisions": int(len(routes)),
        "scenario_families": protocol["scenario_families"], "seed_count": len(protocol["seeds"]),
        "od_count": int(len(ods)), "decision_time_count": len(protocol["decision_times"]),
        "paired_observation_groups": int(len(routes) / len(METHODS)),
        "paired_observation_violations": int(routes.groupby([
            "scenario_family", "seed", "od_id", "decision_phase", "delay_min", "missing_rate", "noise"
        ]).observation_digest.nunique().ne(1).sum()),
        "config_sha256": EXPECTED_CONFIG_SHA256,
        "water_active": False, "parameter_selection_run": False,
        "truth_use": "offline evaluation only; never planner or trigger input",
    }
    write_json(output / "run_manifest.json", run_manifest)
    if not args.no_plots:
        plot_results(output, routes, family_summary, bootstrap, trigger_summary)
    print(json.dumps(run_manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
