"""Small pre-freeze development mechanism suite (not confirmatory evidence)."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from floodroute.common.schema import RouteRequest
from floodroute.experiments.expanded import generate_family_truth, stable_seed, route_overlap
from floodroute.experiments.robustness import truth_metrics
from floodroute.experiments.scenario import observe
from floodroute.experiments.synthetic_water import (EDGE, build_sensor_edge_mapping,
    build_truth_state, map_water_sensors, observe_water, select_sensors, sensor_truth_table)
from floodroute.experiments.synthetic_water_v2 import simulate_latent_ponding_v2
from floodroute.gis.grid_mapping import grid_polygons
from floodroute.risk.dynamic import map_rainfall
from floodroute.risk.fusion import ReliabilityWeightedRiskEngine
from floodroute.risk.trusted import RiskEngine
from floodroute.runtime import Runtime, load_config, write_json

CFG = ROOT / "config/multisource_fusion_v2_development.json"
OUT = ROOT / "results/multisource_fusion_v2/development"
CONDITIONS = [
    {"id": "M1_clean", "rain_delay": 0, "water_delay": 0, "missing": 0., "noise": 0., "bias": False},
    {"id": "M2_water_stale", "rain_delay": 0, "water_delay": 60, "missing": 0., "noise": 0., "bias": False},
    {"id": "M3_water_missing", "rain_delay": 0, "water_delay": 0, "missing": 1., "noise": 0., "bias": False},
    {"id": "M4_water_degraded", "rain_delay": 0, "water_delay": 0, "missing": .2, "noise": .15, "bias": False},
    {"id": "M5_rain_stale", "rain_delay": 60, "water_delay": 0, "missing": 0., "noise": 0., "bias": False},
    {"id": "M6_disagreement", "rain_delay": 0, "water_delay": 0, "missing": 0., "noise": 0., "bias": True},
]


def req(od, at):
    return RouteRequest(od.start_lon, od.start_lat, od.goal_lon, od.goal_lat, pd.Timestamp(at).isoformat(), "risk")


def mapped_rain(runtime, truth, at, delay, seed):
    return map_rainfall(observe(truth, at, delay, 0, 0, seed), runtime.weights, runtime.coverage, at)


def all_rain(runtime, truth, scale):
    result = {}
    for timestamp in sorted(truth.timestamp.unique()):
        at = pd.Timestamp(timestamp); frame = mapped_rain(runtime, truth, at, 0, 0)
        frame["value"] = (frame.value / scale).clip(0, 1); result[at] = frame
    return result


def route_mechanism(route, state, lengths):
    selected = state.reindex(route.edge_ids); weights = lengths.reindex(route.edge_ids).to_numpy(float)
    avg = lambda c, default=0.: float(np.average(selected[c].fillna(default), weights=weights)) if c in selected else np.nan
    return {"rain_effective_weight_mean": avg("rain_effective_weight"),
            "water_effective_weight_mean": avg("water_effective_weight"),
            "water_effective_weight_p90": float(selected.water_effective_weight.quantile(.9)) if "water_effective_weight" in selected else np.nan,
            "fallback_fraction": avg("fallback_static_only"),
            "confidence_mean": avg("confidence"), "uncertainty_mean": avg("uncertainty")}


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config(CFG); frozen = load_config(ROOT / "config/selected_v1_1.json")
    runtime = Runtime(frozen); grids = grid_polygons(ROOT / cfg["grids_path"])
    ods = pd.read_csv(ROOT / "results/expanded_validation/od_pairs.csv")
    ods = ods[ods.od_id.isin(cfg["development"]["od_ids"])]
    sensors = select_sensors(runtime.router.edges, cfg["synthetic_water"]["sensor_selection_seed"])
    mapping = build_sensor_edge_mapping(runtime.edges, sensors, cfg["synthetic_water"]["mapping_radius_m"], cfg["synthetic_water"]["mapping_scale_m"])
    naive = RiskEngine(runtime.edges, cfg)
    universal = ReliabilityWeightedRiskEngine(runtime.edges, cfg, "universal")
    specific = ReliabilityWeightedRiskEngine(runtime.edges, cfg, "source_specific")
    lengths = runtime.edges.set_index(EDGE).length_m
    rows = []
    biased = set(sensors.sort_values("sensor_id").head(16).sensor_id)
    for family in cfg["development"]["scenario_families"]:
        for seed in cfg["development"]["seeds"]:
            truth = generate_family_truth(grids, runtime.edges.total_bounds, family, seed, cfg["scenario"]["start"])
            rain_truth = all_rain(runtime, truth, cfg["sources"]["rain"]["scale"])
            water, _ = simulate_latent_ponding_v2(runtime.edges, rain_truth, family, seed,
                cfg["water_v2"]["local_field_seed"], cfg["synthetic_water"]["integration_step_min"], cfg["synthetic_water"]["inflow_gain"])
            sensor_truth = sensor_truth_table(sensors, naive.index, water, cfg["synthetic_water"]["sensor_cadence_min"], tuple(cfg["synthetic_water"]["sensor_group_offsets_min"]))
            at = pd.Timestamp(sorted(truth.timestamp.unique())[cfg["development"]["decision_step"]])
            truth_state = build_truth_state(naive, rain_truth[at], water[at], {"static": .45, "rain_dynamic": .275, "latent_water": .275})
            for condition in CONDITIONS:
                rframe = mapped_rain(runtime, truth, at, condition["rain_delay"], stable_seed(family, seed, condition["id"], "rain"))
                observed = observe_water(sensor_truth, at, condition["water_delay"], condition["missing"], condition["noise"],
                    stable_seed(family, seed, condition["id"], "water"), bias_sensor_ids=biased if condition["bias"] else ())
                wframe = map_water_sensors(observed, mapping, runtime.edges, at, cfg["synthetic_water"]["mapping_full_weight"])
                states = {"rain_only": runtime.engine.compute({"rain": rframe}),
                          "v2_naive": naive.compute({"rain": rframe, "water": wframe}),
                          "v2_reliability_universal": universal.compute({"rain": rframe, "water": wframe}),
                          "v2_reliability_source_specific": specific.compute({"rain": rframe, "water": wframe})}
                for od in ods.itertuples(index=False):
                    routes = {name: runtime.plan(state, req(od, at)) for name, state in states.items()}
                    rain_route = routes["rain_only"]
                    for name, route in routes.items():
                        rows.append({"scenario_family": family, "seed": seed, "od_id": od.od_id,
                            "condition_id": condition["id"], "method": name,
                            "rain_delay_min": condition["rain_delay"], "water_delay_min": condition["water_delay"],
                            "water_missing_rate": condition["missing"], "water_noise_sigma": condition["noise"],
                            **truth_metrics(route, truth_state, lengths, cfg["routing"]["high_risk"]),
                            "route_overlap_with_rain": route_overlap(route, rain_route, lengths),
                            **route_mechanism(route, states[name], lengths)})
            print(f"Development suite: {family} seed {seed}", flush=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "routes.csv", index=False)
    summary = frame.groupby(["condition_id", "method"], as_index=False).agg(
        truth_exposure=("truth_exposure", "mean"), rain_effective_weight_mean=("rain_effective_weight_mean", "mean"),
        water_effective_weight_mean=("water_effective_weight_mean", "mean"), fallback_fraction=("fallback_fraction", "mean"),
        confidence_mean=("confidence_mean", "mean"), route_overlap_with_rain=("route_overlap_with_rain", "mean"))
    summary.to_csv(OUT / "mechanism_summary.csv", index=False)
    spec = summary[summary.method.eq("v2_reliability_source_specific")].set_index("condition_id")
    rain = summary[summary.method.eq("rain_only")].set_index("condition_id")
    checks = {
        "water_stale_weight_lower_than_clean": bool(spec.loc["M2_water_stale", "water_effective_weight_mean"] < spec.loc["M1_clean", "water_effective_weight_mean"]),
        "water_missing_fallbacks_to_rain_route": bool(spec.loc["M3_water_missing", "route_overlap_with_rain"] == 1),
        "water_degraded_weight_lower_than_clean": bool(spec.loc["M4_water_degraded", "water_effective_weight_mean"] < spec.loc["M1_clean", "water_effective_weight_mean"]),
        "rain_stale_increases_relative_water_weight": bool((spec.loc["M5_rain_stale", "water_effective_weight_mean"] / spec.loc["M5_rain_stale", "rain_effective_weight_mean"]) > (spec.loc["M1_clean", "water_effective_weight_mean"] / spec.loc["M1_clean", "rain_effective_weight_mean"])),
        "missing_gap_to_rain_only": float(spec.loc["M3_water_missing", "truth_exposure"] - rain.loc["M3_water_missing", "truth_exposure"]),
        "clean_gain_vs_rain": float(spec.loc["M1_clean", "truth_exposure"] - rain.loc["M1_clean", "truth_exposure"]),
    }
    write_json(OUT / "mechanism_checks.json", checks)
    with (ROOT / "docs/MULTISOURCE_V2_DEVELOPMENT_LOG.md").open("a", encoding="utf-8") as handle:
        handle.write("\n## D3：六类开发机制套件\n\n")
        handle.write("固定 12 个 family×seed、2 个 OD 的结果：\n\n")
        for key, value in checks.items(): handle.write(f"- `{key}`：{value}\n")
        handle.write("\n这些数值只验证方向，不作为 confirmatory 效果结论；本阶段未根据 truth exposure 修改参数。\n")
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__": run()
