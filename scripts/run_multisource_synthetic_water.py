"""Run the preregistered controlled multi-source synthetic-water study.

This script is deliberately isolated from the production and historical entry
points.  The planner receives only observations.  Complete latent states are
created and used here solely for offline evaluation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
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
    generate_family_truth, route_digest, route_overlap, stable_seed,
)
from floodroute.experiments.replay import ReplayController
from floodroute.experiments.robustness import truth_metrics
from floodroute.experiments.scenario import observe
from floodroute.experiments.synthetic_water import (
    EDGE, SOURCE_KIND, build_sensor_edge_mapping, build_truth_state,
    map_water_sensors, observation_digest, observe_water, select_sensors,
    sensor_truth_table, simulate_latent_ponding,
)
from floodroute.gis.grid_mapping import grid_polygons
from floodroute.risk.dynamic import map_rainfall
from floodroute.risk.trusted import RiskEngine
from floodroute.runtime import Runtime, load_config, write_json


FROZEN_CONFIG = ROOT / "config/selected_v1_1.json"
EXPERIMENT_CONFIG = ROOT / "config/multisource_synthetic_water.json"
PROTOCOL = ROOT / "results/multisource_synthetic_water/protocol.json"
EXPECTED_FROZEN_SHA = "3f8ea08239d12d19b801afec28b5156625dd08daef4f54ff72573756bd7e6dd5"
METHODS = (
    "shortest", "rain_risk", "multisource_naive", "multisource_uncertainty",
    "trusted_universal_tau", "trusted_source_specific_tau",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request_for(od, timestamp, mode: str) -> RouteRequest:
    return RouteRequest(
        float(od.start_lon), float(od.start_lat), float(od.goal_lon), float(od.goal_lat),
        pd.Timestamp(timestamp).isoformat(), mode,
    )


def rain_frames(runtime, truth: pd.DataFrame) -> dict[pd.Timestamp, pd.DataFrame]:
    """Map complete simulated rain to edges; normalized copies drive water truth."""
    result = {}
    for timestamp in sorted(truth.timestamp.unique()):
        at = pd.Timestamp(timestamp)
        complete = observe(truth, at, seed=stable_seed("complete_rain", at))
        result[at] = map_rainfall(complete, runtime.weights, runtime.coverage, at)
    return result


def normalized_rain(frames, scale: float):
    output = {}
    for timestamp, frame in frames.items():
        item = frame.copy()
        item["value"] = (item.value / scale).clip(0, 1)
        output[timestamp] = item
    return output


def latent_at(states, timestamp):
    timestamp = pd.Timestamp(timestamp)
    if timestamp in states:
        return states[timestamp]
    before = max(t for t in states if t <= timestamp)
    return states[before]


def mechanism_metrics(route, mapped_water, state, universal_state=None):
    selected = mapped_water.reindex(route.edge_ids)
    length = state.loc[route.edge_ids].index
    stale = selected.age_min.gt(20) & selected.value.notna()
    result = {
        "stale_water_usage": float(stale.mean()),
        "mean_water_coverage_on_route": float(selected.coverage.fillna(0).mean()),
        "mean_water_age_on_route": float(selected.age_min.mean()) if selected.age_min.notna().any() else np.nan,
        "bad_source_exposure": float(((1 - selected.coverage.fillna(0)) + selected.quality.fillna(1)).mean() / 2),
        "source_disagreement": np.nan,
        "trusted_penalty_due_to_staleness_uncertainty": float(
            (state.loc[route.edge_ids].trusted_risk - state.loc[route.edge_ids].risk).mean()
        ),
        "trusted_penalty_source_specific_minus_universal": np.nan,
    }
    if universal_state is not None:
        result["trusted_penalty_source_specific_minus_universal"] = float(
            (state.loc[route.edge_ids].trusted_risk - universal_state.loc[route.edge_ids].trusted_risk).mean()
        )
    return result


def prepare_models(runtime, config):
    source_engine = RiskEngine(runtime.edges, config)
    universal_config = copy.deepcopy(config)
    universal_tau = config["experiment"]["universal_tau_min"]
    for settings in universal_config["sources"].values():
        if settings["active"]:
            settings["tau_min"] = universal_tau
    return source_engine, RiskEngine(runtime.edges, universal_config), universal_config


def evaluate_main(runtime, config, protocol, grids, sensors, mapping, ods):
    design = protocol["design"]
    water_cfg = protocol["synthetic_water"]
    lengths = runtime.edges.set_index(EDGE).length_m
    source_engine, universal_engine, _ = prepare_models(runtime, config)
    rain_engine = runtime.engine
    index = source_engine.index
    bounds = runtime.edges.total_bounds
    rows, condition_rows, latent_rows, manifest_rows, archived_truth = [], [], [], [], []
    shortest_cache = {}; rain_route_cache = {}

    for family in design["scenario_families"]:
        for seed in design["seeds"]:
            truth = generate_family_truth(grids, bounds, family, seed, config["scenario"]["start"])
            complete_rain = rain_frames(runtime, truth)
            normalized = normalized_rain(complete_rain, config["sources"]["rain"]["scale"])
            latent = simulate_latent_ponding(
                runtime.edges, normalized, water_cfg["integration_step_min"], water_cfg["inflow_gain"],
            )
            sensor_truth = sensor_truth_table(
                sensors, index, latent, water_cfg["sensor_cadence_min"],
                tuple(water_cfg["sensor_group_offsets_min"]),
            )
            archive = sensor_truth.copy(); archive["scenario_family"] = family; archive["seed"] = seed
            archived_truth.append(archive)
            for timestamp, values in latent.items():
                latent_rows.append({
                    "scenario_family": family, "seed": seed, "timestamp": timestamp,
                    "min": float(values.min()), "mean": float(values.mean()),
                    "p95": float(np.quantile(values, .95)), "max": float(values.max()),
                    "data_type": "SIMULATED_TRUTH", "unit": "dimensionless_index_0_1",
                })
            manifest_rows.append({
                "scenario_family": family, "seed": seed, "steps": int(truth.timestamp.nunique()),
                "start": pd.Timestamp(truth.timestamp.min()).isoformat(),
                "end": pd.Timestamp(truth.timestamp.max()).isoformat(),
                "rain_max_mm": float(truth.rain_mm.max()), "sensor_truth_records": len(sensor_truth),
                "data_type": "SIMULATED_SCENARIO", "truth_type": "SIMULATED_TRUTH",
            })
            times = sorted(truth.timestamp.unique())
            for step in design["decision_steps"]:
                at = pd.Timestamp(times[step])
                perfect_rain_obs = observe(truth, at, seed=stable_seed(family, seed, step, "rain"))
                mapped_rain = map_rainfall(perfect_rain_obs, runtime.weights, runtime.coverage, at)
                normalized_at = mapped_rain.copy()
                normalized_at["value"] = (normalized_at.value / config["sources"]["rain"]["scale"]).clip(0, 1)
                truth_state = build_truth_state(
                    source_engine, normalized_at, latent_at(latent, at), design["truth_weights"],
                )
                rain_state = rain_engine.compute({"rain": mapped_rain})
                perfect_water = pd.DataFrame({
                    "value": latent_at(latent, at), "age_min": 0.0,
                    "coverage": 1.0, "quality": 0.0,
                }, index=index)
                perfect_state = source_engine.compute({"rain": mapped_rain, "water": perfect_water})

                for condition in design["conditions"]:
                    obs_seed = stable_seed(family, seed, step, condition["condition_id"], "water_observation")
                    observed = observe_water(
                        sensor_truth, at, condition["delay_min"], condition["missing_rate"],
                        condition["noise_sigma"], obs_seed,
                    )
                    begin = time.perf_counter()
                    mapped_water = map_water_sensors(
                        observed, mapping, runtime.edges, at, water_cfg["mapping_full_weight"],
                    )
                    mapping_ms = (time.perf_counter() - begin) * 1000
                    begin = time.perf_counter()
                    source_state = source_engine.compute({"rain": mapped_rain, "water": mapped_water})
                    universal_state = universal_engine.compute({"rain": mapped_rain, "water": mapped_water})
                    state_ms = (time.perf_counter() - begin) * 1000
                    water_digest = observation_digest(observed)
                    condition_rows.append({
                        "scenario_family": family, "seed": seed, "decision_step": step,
                        "timestamp": at, **condition, "observation_seed": obs_seed,
                        "observation_digest": water_digest, "eligible_records": int(len(observed)),
                        "available_records": int(pd.to_datetime(observed.retrieved_at, utc=True).le(at).sum()),
                        "mapped_edge_coverage_mean": float(mapped_water.coverage.fillna(0).mean()),
                    })
                    states = {
                        "shortest": (rain_state, "shortest"),
                        "rain_risk": (rain_state, "risk"),
                        "multisource_naive": (source_state, "risk"),
                        "multisource_uncertainty": (source_state, "risk_uncertainty"),
                        "trusted_universal_tau": (universal_state, "trusted"),
                        "trusted_source_specific_tau": (source_state, "trusted"),
                    }
                    for od in ods.itertuples(index=False):
                        cache_key = od.od_id
                        if cache_key not in shortest_cache:
                            start = time.perf_counter()
                            shortest_cache[cache_key] = runtime.plan(rain_state, request_for(od, at, "shortest"))
                            shortest_cache[cache_key + "_ms"] = (time.perf_counter() - start) * 1000
                        shortest = shortest_cache[cache_key]
                        method_order = np.random.default_rng(stable_seed(obs_seed, od.od_id, "order")).permutation(METHODS)
                        for method in method_order:
                            state, mode = states[str(method)]
                            start = time.perf_counter()
                            rain_key = (family, seed, step, od.od_id)
                            if method == "shortest":
                                route = shortest; planning_ms = shortest_cache[cache_key + "_ms"]
                            elif method == "rain_risk" and rain_key in rain_route_cache:
                                route, planning_ms = rain_route_cache[rain_key]
                            else:
                                route = runtime.plan(state, request_for(od, at, mode))
                                planning_ms = (time.perf_counter() - start) * 1000
                                if method == "rain_risk": rain_route_cache[rain_key] = (route, planning_ms)
                            metrics = truth_metrics(route, truth_state, lengths, config["routing"]["high_risk"])
                            mech = mechanism_metrics(route, mapped_water, state, universal_state)
                            rain_sel = normalized_at.reindex(route.edge_ids).value
                            water_sel = mapped_water.reindex(route.edge_ids).value
                            mech["source_disagreement"] = float((rain_sel - water_sel).abs().mean()) if water_sel.notna().any() else np.nan
                            rows.append({
                                "scenario_family": family, "seed": seed, "od_id": od.od_id,
                                "decision_step": step, "timestamp": at, **condition,
                                "method": str(method), "observation_seed": obs_seed,
                                "observation_digest": water_digest, **metrics, **mech,
                                "route_overlap_with_shortest": route_overlap(route, shortest, lengths),
                                "mapping_ms": mapping_ms, "state_ms": state_ms,
                                "planning_ms": planning_ms, "computation_ms": mapping_ms + state_ms + planning_ms,
                                "route_digest": route_digest(route.edge_ids), "route_edge_count": len(route.edge_ids),
                            })

                # Perfect water is a separate upper-bound reference, once per OD and decision.
                for od in ods.itertuples(index=False):
                    shortest = shortest_cache[od.od_id]
                    start = time.perf_counter()
                    route = runtime.plan(perfect_state, request_for(od, at, "risk"))
                    planning_ms = (time.perf_counter() - start) * 1000
                    rows.append({
                        "scenario_family": family, "seed": seed, "od_id": od.od_id,
                        "decision_step": step, "timestamp": at, "condition_id": "PERFECT",
                        "delay_min": 0, "missing_rate": 0.0, "noise_sigma": 0.0,
                        "method": "perfect_water_reference", "observation_seed": -1,
                        "observation_digest": "PERFECT_FULL_EDGE_TRUTH_REFERENCE",
                        **truth_metrics(route, truth_state, lengths, config["routing"]["high_risk"]),
                        "stale_water_usage": 0.0, "mean_water_coverage_on_route": 1.0,
                        "mean_water_age_on_route": 0.0, "bad_source_exposure": 0.0,
                        "source_disagreement": float((normalized_at.reindex(route.edge_ids).value.to_numpy() - latent_at(latent, at)[index.get_indexer(route.edge_ids)]).mean()),
                        "trusted_penalty_due_to_staleness_uncertainty": 0.0,
                        "trusted_penalty_source_specific_minus_universal": 0.0,
                        "route_overlap_with_shortest": route_overlap(route, shortest, lengths),
                        "mapping_ms": 0.0, "state_ms": 0.0, "planning_ms": planning_ms,
                        "computation_ms": planning_ms, "route_digest": route_digest(route.edge_ids),
                        "route_edge_count": len(route.edge_ids),
                    })
            print(f"Main study: {family} seed {seed} ({len(rows):,} routes)", flush=True)

    routes = pd.DataFrame(rows)
    if len(routes) != protocol["planned_total_routes"]:
        raise AssertionError(f"Expected {protocol['planned_total_routes']:,} routes, got {len(routes):,}")
    formal = routes[routes.method.isin(METHODS)]
    key = ["scenario_family", "seed", "od_id", "decision_step", "condition_id"]
    if not formal.groupby(key).observation_digest.nunique().eq(1).all():
        raise AssertionError("Paired methods did not use identical water observations")
    baseline = formal[formal.condition_id.eq("C00")].set_index(key[:-1] + ["method"]).route_digest
    routes["route_change_from_baseline"] = False
    mask = routes.method.isin(METHODS)
    routes.loc[mask, "route_change_from_baseline"] = [
        digest != baseline.loc[(fam, seed, od, step, method)]
        for fam, seed, od, step, method, digest in routes.loc[mask, key[:-1] + ["method", "route_digest"]].itertuples(index=False, name=None)
    ]
    return (
        routes.sort_values(key + ["method"]).reset_index(drop=True),
        pd.DataFrame(condition_rows), pd.DataFrame(latent_rows), pd.DataFrame(manifest_rows),
        pd.concat(archived_truth, ignore_index=True),
    )


def summarize(routes, protocol):
    metrics = [
        "truth_exposure", "distance_m", "max_truth_risk", "p95_truth_risk",
        "high_risk_length_ratio", "route_overlap_with_shortest", "route_change_from_baseline",
        "stale_water_usage", "bad_source_exposure", "mean_water_coverage_on_route", "computation_ms",
    ]
    formal = routes[routes.method.isin(METHODS)]
    seed_summary = formal.groupby(["scenario_family", "seed", "method"], as_index=False)[metrics].mean()
    perfect = routes[routes.method.eq("perfect_water_reference")].groupby(
        ["scenario_family", "seed", "method"], as_index=False
    )[metrics].mean()
    seed_summary = pd.concat([seed_summary, perfect], ignore_index=True)
    family_summary = seed_summary.groupby(["scenario_family", "method"], as_index=False).agg(
        n_seeds=("seed", "nunique"), mean_truth_exposure=("truth_exposure", "mean"),
        seed_sd_truth_exposure=("truth_exposure", "std"), mean_distance_m=("distance_m", "mean"),
        mean_high_risk_length_ratio=("high_risk_length_ratio", "mean"),
        mean_stale_water_usage=("stale_water_usage", "mean"),
        mean_bad_source_exposure=("bad_source_exposure", "mean"),
        mean_computation_ms=("computation_ms", "mean"),
    )
    specs = [
        ("perfect_water-reference_minus-rain", "perfect_water_reference", "rain_risk"),
        ("naive_async-minus-rain", "multisource_naive", "rain_risk"),
        ("uncertainty-minus-naive", "multisource_uncertainty", "multisource_naive"),
        ("universal_tau-minus-uncertainty", "trusted_universal_tau", "multisource_uncertainty"),
        ("source_specific-minus-universal", "trusted_source_specific_tau", "trusted_universal_tau"),
        ("source_specific-minus-rain", "trusted_source_specific_tau", "rain_risk"),
    ]
    wide = seed_summary.pivot(index=["scenario_family", "seed"], columns="method", values="truth_exposure")
    comparison_rows = []
    for (family, seed), row in wide.iterrows():
        for name, left, right in specs:
            comparison_rows.append({
                "scenario_family": family, "seed": seed, "comparison": name,
                "mean_difference": float(row[left] - row[right]),
            })
    comparisons = pd.DataFrame(comparison_rows)
    bootstrap = []
    rng = np.random.default_rng(protocol["design"]["bootstrap_seed"])
    seeds = np.array(protocol["design"]["seeds"])
    iterations = protocol["design"]["bootstrap_iterations"]
    for family in [*protocol["design"]["scenario_families"], "all_families"]:
        subset = comparisons if family == "all_families" else comparisons[comparisons.scenario_family.eq(family)]
        for name, group in subset.groupby("comparison"):
            by_seed = group.groupby("seed").mean_difference.mean().reindex(seeds)
            samples = np.array([by_seed.loc[rng.choice(seeds, len(seeds), replace=True)].mean() for _ in range(iterations)])
            bootstrap.append({
                "scenario_family": family, "comparison": name,
                "mean_difference": float(by_seed.mean()),
                "ci_low": float(np.quantile(samples, .025)), "ci_high": float(np.quantile(samples, .975)),
                "bootstrap_unit": "seed", "iterations": iterations,
                "bootstrap_seed": protocol["design"]["bootstrap_seed"],
            })
    return seed_summary, family_summary, comparisons, pd.DataFrame(bootstrap)


class PlannerView:
    def __init__(self, runtime, config):
        self.edges = runtime.edges; self.router = runtime.router; self.config = config

    def plan(self, state, request):
        return self.router.plan_frame(request, state, self.config["routing"])


def trigger_stress(runtime, config, protocol, grids, sensors, mapping, ods):
    design = protocol["design"]; spec = design["trigger"]; wc = protocol["synthetic_water"]
    source_engine, _, _ = prepare_models(runtime, config)
    planner = PlannerView(runtime, config)
    lengths = runtime.edges.set_index(EDGE).length_m
    bounds = runtime.edges.total_bounds
    chosen_ods = ods[ods.od_id.isin(spec["od_ids"])]
    summary_rows, detail_rows, failure_rows = [], [], []
    east = set(sensors.nlargest(len(sensors) // 2, "lon").sensor_id)
    biased = set(sensors.sort_values("sensor_id").head(16).sensor_id)

    for family in design["scenario_families"]:
        for seed in spec["seeds"]:
            truth = generate_family_truth(grids, bounds, family, seed, config["scenario"]["start"])
            complete = rain_frames(runtime, truth)
            latent = simulate_latent_ponding(runtime.edges, normalized_rain(complete, config["sources"]["rain"]["scale"]), wc["integration_step_min"], wc["inflow_gain"])
            sensor_truth = sensor_truth_table(sensors, source_engine.index, latent, wc["sensor_cadence_min"], tuple(wc["sensor_group_offsets_min"]))
            times = [pd.Timestamp(t) for t in sorted(truth.timestamp.unique())]
            outage_start, outage_end = times[3], times[5]
            for case in spec["stress_cases"]:
                for od in chosen_ods.itertuples(index=False):
                    controllers = {policy: ReplayController(planner, policy) for policy in spec["policies"]}
                    records = {policy: [] for policy in controllers}
                    previous_truth = {policy: None for policy in controllers}
                    rain_only_values = []
                    for step, at in enumerate(times):
                        rain_delay = 30 if case == "rain_stale_water_fresh" else 0
                        rain_obs = observe(truth, at, rain_delay, 0, 0, stable_seed(family, seed, case, step, "rain"))
                        mapped_rain = map_rainfall(rain_obs, runtime.weights, runtime.coverage, at)
                        water_delay = 60 if case in {"water_delay", "water_stale_rain_fresh"} else 10
                        outage_ids = east if case in {"water_block_missing", "water_recovery"} else set()
                        kwargs = {}
                        if outage_ids:
                            kwargs = {"outage_sensor_ids": outage_ids, "outage_start": outage_start,
                                      "outage_end": outage_end if case == "water_recovery" else times[-1]}
                        if case == "source_disagreement": kwargs["bias_sensor_ids"] = biased
                        water_obs = observe_water(
                            sensor_truth, at, water_delay, .2, .05,
                            stable_seed(family, seed, case, step, "water"), **kwargs,
                        )
                        mapped_water = map_water_sensors(water_obs, mapping, runtime.edges, at, wc["mapping_full_weight"])
                        begin = time.perf_counter()
                        state = source_engine.compute({"rain": mapped_rain, "water": mapped_water})
                        shared_ms = (time.perf_counter() - begin) * 1000
                        truth_rain_at = complete[at].copy()
                        truth_rain_at["value"] = (truth_rain_at.value / config["sources"]["rain"]["scale"]).clip(0, 1)
                        truth_state = build_truth_state(source_engine, truth_rain_at, latent_at(latent, at), design["truth_weights"])
                        rain_state = runtime.engine.compute({"rain": mapped_rain})
                        rain_route = runtime.plan(rain_state, request_for(od, at, "risk"))
                        rain_only_values.append(truth_metrics(rain_route, truth_state, lengths, config["routing"]["high_risk"])["truth_exposure"])
                        for policy, controller in controllers.items():
                            before_route = controller.current_route
                            before_truth = None if before_route is None else truth_metrics(before_route, truth_state, lengths, config["routing"]["high_risk"])["truth_exposure"]
                            begin = time.perf_counter(); log = controller.step(state, request_for(od, at, "trusted")); elapsed = (time.perf_counter() - begin) * 1000
                            metrics = truth_metrics(controller.current_route, truth_state, lengths, config["routing"]["high_risk"])
                            unnecessary = bool(log["route_changed"] and before_truth is not None and metrics["truth_exposure"] >= before_truth)
                            record = {
                                "scenario_family": family, "seed": seed, "stress_case": case,
                                "od_id": od.od_id, "step": step, "timestamp": at, "policy": policy,
                                **log, **metrics, "rain_only_truth_exposure": rain_only_values[-1],
                                "unnecessary_replan": unnecessary,
                                "route_digest": route_digest(controller.current_route.edge_ids),
                                "computation_ms": shared_ms + elapsed,
                            }
                            detail_rows.append(record); records[policy].append(record)
                            previous_truth[policy] = metrics["truth_exposure"]
                    always_mean = pd.DataFrame(records["always"]).truth_exposure.mean()
                    for policy, data in records.items():
                        frame = pd.DataFrame(data)
                        route_series = frame.route_digest.tolist()
                        changes = [route_series[i] != route_series[i - 1] for i in range(1, len(route_series))]
                        oscillation = any(route_series[i] == route_series[i - 2] != route_series[i - 1] for i in range(2, len(route_series)))
                        mean_exposure = float(frame.truth_exposure.mean())
                        flags = {
                            "missed_useful_replan": bool(policy == "triggered" and mean_exposure > always_mean + .01),
                            "stale_source_induced_bad_route": bool(policy == "triggered" and case == "water_stale_rain_fresh" and mean_exposure > frame.rain_only_truth_exposure.mean() + .01),
                            "unnecessary_replan": bool(frame.unnecessary_replan.any()),
                            "route_oscillation": bool(oscillation),
                        }
                        row = {
                            "scenario_family": family, "seed": seed, "stress_case": case,
                            "od_id": od.od_id, "policy": policy, "mean_truth_exposure": mean_exposure,
                            "mean_rain_only_truth_exposure": float(frame.rain_only_truth_exposure.mean()),
                            "final_replan_count": int(frame.replan_count.iloc[-1]),
                            "final_route_change_count": int(frame.route_change_count.iloc[-1]),
                            "planner_calls": int(frame.planner_calls.iloc[-1]),
                            "total_computation_ms": float(frame.computation_ms.sum()), **flags,
                        }
                        summary_rows.append(row)
                        for flag, active in flags.items():
                            if active:
                                failure_rows.append({**{k: row[k] for k in ["scenario_family", "seed", "stress_case", "od_id", "policy"]}, "failure_type": flag, "difference": mean_exposure - always_mean})
            print(f"Trigger study: {family} seed {seed}", flush=True)
    return pd.DataFrame(summary_rows), pd.DataFrame(detail_rows), pd.DataFrame(failure_rows)


def main_failures(routes):
    formal = routes[routes.method.isin(METHODS)]
    key = ["scenario_family", "seed", "od_id", "decision_step", "condition_id"]
    wide = formal.pivot(index=key, columns="method", values="truth_exposure")
    rows = []
    for index, row in wide.iterrows():
        common = dict(zip(key, index))
        if row.trusted_source_specific_tau > row.multisource_naive + .01:
            rows.append({**common, "policy": "main", "failure_type": "trusted_worse_than_naive", "difference": float(row.trusted_source_specific_tau - row.multisource_naive)})
        if row.multisource_naive > row.rain_risk + .01:
            rows.append({**common, "policy": "main", "failure_type": "multisource_worse_than_rain_only", "difference": float(row.multisource_naive - row.rain_risk)})
    return pd.DataFrame(rows)


def save_figures(output, routes, latent_summary, sensor_registry, trigger_summary):
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    figure_dir = output / "figures"; figure_dir.mkdir(parents=True, exist_ok=True)
    sample = latent_summary[(latent_summary.scenario_family == "moving_center") & (latent_summary.seed == 8101)]
    fig, ax = plt.subplots(figsize=(8, 4)); ax.plot(pd.to_datetime(sample.timestamp), sample["mean"], marker="o", label="模拟积涝监测源 latent mean"); ax.set_ylabel("无量纲积涝状态指数"); ax.set_title("降雨与模拟积涝时间滞后示例"); ax.legend(); fig.autofmt_xdate(); fig.tight_layout(); fig.savefig(figure_dir / "降雨与模拟积涝时间滞后示例.png", dpi=180); plt.close(fig)

    labels = {
        "rain_risk": "仅降雨", "multisource_naive": "朴素多源", "multisource_uncertainty": "多源+不确定性",
        "trusted_universal_tau": "统一时间尺度", "trusted_source_specific_tau": "分数据源时间尺度",
    }
    formal = routes[routes.method.isin(labels)]
    means = formal.groupby("method").truth_exposure.mean().reindex(labels)
    fig, ax = plt.subplots(figsize=(8, 4)); ax.bar([labels[x] for x in means.index], means.values); ax.set_ylabel("平均真值风险暴露"); ax.set_title("异步多源机制对比"); ax.tick_params(axis="x", rotation=15); fig.tight_layout(); fig.savefig(figure_dir / "异步多源机制对比.png", dpi=180); plt.close(fig)

    for column, title, filename in [
        ("delay_min", "水位延迟与风险暴露", "水位延迟与风险暴露.png"),
        ("missing_rate", "水位缺失率与风险暴露", "水位缺失率与风险暴露.png"),
        ("noise_sigma", "水位噪声与风险暴露", "水位噪声与风险暴露.png"),
    ]:
        table = formal.groupby([column, "method"]).truth_exposure.mean().unstack()
        fig, ax = plt.subplots(figsize=(8, 4)); table.plot(ax=ax, marker="o"); ax.set_title(title); ax.set_ylabel("平均真值风险暴露"); ax.legend([labels.get(x, x) for x in table.columns], fontsize=8); fig.tight_layout(); fig.savefig(figure_dir / filename, dpi=180); plt.close(fig)

    tau = formal[formal.method.isin(["trusted_universal_tau", "trusted_source_specific_tau"])].groupby("method").truth_exposure.mean()
    fig, ax = plt.subplots(figsize=(6, 4)); ax.bar(["统一时间尺度", "分数据源时间尺度"], tau.reindex(["trusted_universal_tau", "trusted_source_specific_tau"])); ax.set_ylabel("平均真值风险暴露"); ax.set_title("统一时间尺度与分数据源时间尺度"); fig.tight_layout(); fig.savefig(figure_dir / "统一时间尺度与分数据源时间尺度.png", dpi=180); plt.close(fig)

    trig = trigger_summary.groupby(["stress_case", "policy"]).mean_truth_exposure.mean().unstack()
    fig, ax = plt.subplots(figsize=(10, 4)); trig.plot(kind="bar", ax=ax); ax.set_title("Trigger 异步多源时间线"); ax.set_ylabel("平均真值风险暴露"); ax.tick_params(axis="x", rotation=25); fig.tight_layout(); fig.savefig(figure_dir / "Trigger 异步多源时间线.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5)); points = ax.scatter(sensor_registry.lon, sensor_registry.lat, c=sensor_registry.static_susceptibility, cmap="viridis"); ax.set_title("模拟传感器空间分布"); ax.set_xlabel("经度"); ax.set_ylabel("纬度"); fig.colorbar(points, label="静态易涝程度"); fig.tight_layout(); fig.savefig(figure_dir / "模拟传感器空间分布.png", dpi=180); plt.close(fig)


def stable_frame_hash(frame: pd.DataFrame) -> str:
    """Hash scientific output while excluding explicitly non-reproducible timings."""
    excluded = {c for c in frame if c.endswith("_ms") or c == "total_computation_ms"}
    stable = frame.drop(columns=sorted(excluded)).copy()
    stable = stable.reindex(sorted(stable.columns), axis=1)
    for column in stable.select_dtypes(include=["datetime", "datetimetz"]):
        stable[column] = pd.to_datetime(stable[column], utc=True).astype(str)
    if len(stable):
        stable = stable.sort_values(list(stable.columns), kind="mergesort", na_position="first").reset_index(drop=True)
    payload = stable.to_csv(index=False, lineterminator="\n", float_format="%.12g").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stable_output_hashes(output: Path):
    readers = {
        "sensor_registry.csv": pd.read_csv, "latent_water_summary.csv": pd.read_csv,
        "observation_conditions.csv": pd.read_csv, "routes.parquet": pd.read_parquet,
        "seed_summary.csv": pd.read_csv, "family_summary.csv": pd.read_csv,
        "method_comparisons.csv": pd.read_csv, "bootstrap_ci.csv": pd.read_csv,
        "trigger_summary.csv": pd.read_csv, "failure_cases.csv": pd.read_csv,
        "trigger_detail.parquet": pd.read_parquet,
    }
    return {name: stable_frame_hash(reader(output / name)) for name, reader in readers.items()}


def run(output: Path):
    if sha256(FROZEN_CONFIG) != EXPECTED_FROZEN_SHA:
        raise RuntimeError("Frozen selected_v1_1.json SHA256 changed; aborting")
    frozen = load_config(FROZEN_CONFIG); config = load_config(EXPERIMENT_CONFIG)
    if frozen["sources"]["water"]["active"] or not config["sources"]["water"]["active"] or not config.get("experiment_only"):
        raise RuntimeError("Production/experiment water activation boundary violated")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    runtime = Runtime(frozen); grids = grid_polygons(ROOT / config["grids_path"])
    ods = pd.read_csv(ROOT / protocol["design"]["od_source"])
    sensors = select_sensors(runtime.router.edges, protocol["synthetic_water"]["sensor_selection_seed"])
    mapping = build_sensor_edge_mapping(runtime.edges, sensors, protocol["synthetic_water"]["mapping_radius_m"], protocol["synthetic_water"]["mapping_scale_m"])
    registry = pd.DataFrame(sensors.drop(columns="_point"))
    routes, conditions, latent_summary, manifest, latent_truth = evaluate_main(runtime, config, protocol, grids, sensors, mapping, ods)
    seed_summary, family_summary, comparisons, bootstrap = summarize(routes, protocol)
    trigger_summary, trigger_detail, trigger_failures = trigger_stress(runtime, config, protocol, grids, sensors, mapping, ods)
    failures = pd.concat([main_failures(routes), trigger_failures], ignore_index=True, sort=False)

    registry.to_csv(output / "sensor_registry.csv", index=False)
    latent_summary.to_csv(output / "latent_water_summary.csv", index=False)
    conditions.to_csv(output / "observation_conditions.csv", index=False)
    routes.to_parquet(output / "routes.parquet", index=False)
    seed_summary.to_csv(output / "seed_summary.csv", index=False)
    family_summary.to_csv(output / "family_summary.csv", index=False)
    comparisons.to_csv(output / "method_comparisons.csv", index=False)
    bootstrap.to_csv(output / "bootstrap_ci.csv", index=False)
    trigger_summary.to_csv(output / "trigger_summary.csv", index=False)
    trigger_detail.to_parquet(output / "trigger_detail.parquet", index=False)
    failures.to_csv(output / "failure_cases.csv", index=False)
    write_json(output / "scenario_manifest.json", manifest.to_dict("records"))
    write_json(output / "config_snapshot.json", config)
    (output / "config_sha256.txt").write_text(sha256(EXPERIMENT_CONFIG) + "\n", encoding="utf-8")
    if output.resolve() == (ROOT / "results/multisource_synthetic_water").resolve():
        scenario_dir = ROOT / "data/scenarios/multisource_water"; scenario_dir.mkdir(parents=True, exist_ok=True)
        registry.to_csv(scenario_dir / "sensor_registry.csv", index=False)
        latent_truth.to_parquet(scenario_dir / "latent_water_truth.parquet", index=False)
        write_json(scenario_dir / "scenario_manifest.json", manifest.to_dict("records"))
    save_figures(output, routes, latent_summary, registry, trigger_summary)
    write_json(output / "run_manifest.json", {
        "route_count": len(routes), "formal_route_count": int(routes.method.isin(METHODS).sum()),
        "perfect_reference_count": int(routes.method.eq("perfect_water_reference").sum()),
        "trigger_summary_count": len(trigger_summary), "trigger_detail_count": len(trigger_detail),
        "failure_count": len(failures), "stable_output_hashes": stable_output_hashes(output),
    })
    print(json.dumps(json.loads((output / "run_manifest.json").read_text()), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results/multisource_synthetic_water")
    args = parser.parse_args(); run(args.output)
