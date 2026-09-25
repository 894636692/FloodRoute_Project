"""Run the frozen Multisource Fusion V2 confirmatory experiment."""
from __future__ import annotations

import argparse, copy, hashlib, json, sys, time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from floodroute.common.schema import RouteRequest
from floodroute.experiments.expanded import generate_family_truth, route_digest, route_overlap, stable_seed
from floodroute.experiments.replay import ReplayController
from floodroute.experiments.robustness import truth_metrics
from floodroute.experiments.scenario import observe
from floodroute.experiments.synthetic_water import (EDGE, build_sensor_edge_mapping, build_truth_state,
    map_water_sensors, observe_water, select_sensors, sensor_truth_table, simulate_latent_ponding)
from floodroute.experiments.synthetic_water_v2 import simulate_latent_ponding_v2
from floodroute.gis.grid_mapping import grid_polygons
from floodroute.risk.dynamic import map_rainfall
from floodroute.risk.fusion import ReliabilityWeightedRiskEngine
from floodroute.risk.trusted import RiskEngine
from floodroute.runtime import Runtime, load_config, write_json

FROZEN = ROOT / "config/selected_v1_1.json"
CONFIG = ROOT / "config/multisource_fusion_v2.json"
PROTOCOL = ROOT / "results/multisource_fusion_v2/protocol.json"
EXPECTED_FROZEN_SHA = "3f8ea08239d12d19b801afec28b5156625dd08daef4f54ff72573756bd7e6dd5"
METHODS = ["S0_shortest", "S1_rain_only", "S2_v1_redundant_naive", "S3_v2_local_naive",
           "S4_v2_reliability_universal", "S5_v2_reliability_source_specific"]


def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def request(od, at, mode="risk"):
    return RouteRequest(float(od.start_lon), float(od.start_lat), float(od.goal_lon), float(od.goal_lat), pd.Timestamp(at).isoformat(), mode)


def rain_frames(runtime, truth, scale):
    raw, normalized = {}, {}
    for timestamp in sorted(truth.timestamp.unique()):
        at = pd.Timestamp(timestamp); frame = map_rainfall(observe(truth, at, seed=0), runtime.weights, runtime.coverage, at)
        raw[at] = frame; item = frame.copy(); item["value"] = (item.value / scale).clip(0, 1); normalized[at] = item
    return raw, normalized


def route_mechanism(route, state, lengths):
    selected = state.reindex(route.edge_ids); weights = lengths.reindex(route.edge_ids).to_numpy(float)
    avg = lambda col, default=0.: float(np.average(selected[col].fillna(default), weights=weights)) if col in selected else np.nan
    water = selected.water_effective_weight.fillna(0).to_numpy(float) if "water_effective_weight" in selected else np.zeros(len(selected))
    rain = selected.rain_effective_weight.fillna(0).to_numpy(float) if "rain_effective_weight" in selected else np.zeros(len(selected))
    disagreement = np.abs(selected.dynamic_risk.to_numpy(float) - selected.static_risk.to_numpy(float)) if "dynamic_risk" in selected else np.zeros(len(selected))
    return {"rain_effective_weight_mean": avg("rain_effective_weight"), "water_effective_weight_mean": avg("water_effective_weight"),
            "water_effective_weight_p90": float(np.quantile(water, .9)), "fallback_fraction": avg("fallback_static_only"),
            "low_reliability_water_usage": float(np.average((water > 0) & (selected.get("water_reliability", pd.Series(1., index=selected.index)).to_numpy(float) < .5), weights=weights)),
            "source_disagreement_fraction": float(np.average(disagreement > .25, weights=weights)),
            "confidence_mean": avg("confidence"), "freshness_mean": avg("freshness"), "uncertainty_mean": avg("uncertainty")}


def record(route, state, truth_state, lengths, cfg, meta):
    return {**meta, **truth_metrics(route, truth_state, lengths, cfg["routing"]["high_risk"]),
            "route_digest": route_digest(route.edge_ids), "edge_ids_json": json.dumps([list(x) for x in route.edge_ids]),
            **route_mechanism(route, state, lengths)}


def evaluate(runtime, cfg, protocol, grids, sensors, mapping, ods):
    ex = cfg["experiment"]; wc = cfg["synthetic_water"]; lengths = runtime.edges.set_index(EDGE).length_m
    naive = RiskEngine(runtime.edges, cfg); universal = ReliabilityWeightedRiskEngine(runtime.edges, cfg, "universal")
    specific = ReliabilityWeightedRiskEngine(runtime.edges, cfg, "source_specific")
    rows, latent_rows, patch_rows = [], [], []
    biased = set(sensors.sort_values("sensor_id").head(16).sensor_id)
    for family in ex["scenario_families"]:
        for seed in ex["seeds"]:
            truth = generate_family_truth(grids, runtime.edges.total_bounds, family, seed, cfg["scenario"]["start"])
            complete_raw, complete_norm = rain_frames(runtime, truth, cfg["sources"]["rain"]["scale"])
            water_v1 = simulate_latent_ponding(runtime.edges, complete_norm, wc["integration_step_min"], wc["inflow_gain"])
            water_v2, latent = simulate_latent_ponding_v2(runtime.edges, complete_norm, family, seed,
                cfg["water_v2"]["local_field_seed"], wc["integration_step_min"], wc["inflow_gain"])
            sensors_v1 = sensor_truth_table(sensors, naive.index, water_v1, wc["sensor_cadence_min"], tuple(wc["sensor_group_offsets_min"]))
            sensors_v2 = sensor_truth_table(sensors, naive.index, water_v2, wc["sensor_cadence_min"], tuple(wc["sensor_group_offsets_min"]))
            for at in sorted(complete_norm):
                latent_rows.append({"scenario_family": family, "seed": seed, "timestamp": at,
                    "water_mean": float(water_v2[at].mean()), "water_p95": float(np.quantile(water_v2[at], .95)),
                    "water_max": float(water_v2[at].max()), "local_state_mean": float(latent["local_hydrologic_state"].mean()),
                    "disturbance_mean": float(latent["disturbance_states"][at].mean())})
            patches = latent["patches"].copy(); patches["scenario_family"] = family; patches["seed"] = seed; patch_rows.append(patches)
            times = sorted(truth.timestamp.unique())
            for step in ex["decision_steps"]:
                at = pd.Timestamp(times[step])
                truth_state = build_truth_state(naive, complete_norm[at], water_v2[at], ex["truth_weights"])
                perfect_water = pd.DataFrame({"value": water_v2[at], "age_min": 0., "coverage": 1., "quality": 0.}, index=naive.index)
                perfect_state = specific.compute({"rain": complete_raw[at], "water": perfect_water})
                for od in ods.itertuples(index=False):
                    route = runtime.plan(perfect_state, request(od, at))
                    rows.append(record(route, perfect_state, truth_state, lengths, cfg, {"scenario_family": family, "seed": seed,
                        "decision_step": step, "timestamp": at, "od_id": od.od_id, "condition_id": "PERFECT", "method": "S6_perfect_water_v2"}))
                cache = {}
                for condition in ex["conditions"]:
                    rain_delay = condition["rain_delay_min"]
                    mapped_rain = map_rainfall(observe(truth, at, rain_delay, 0, 0, stable_seed(family, seed, step, condition["condition_id"], "rain")), runtime.weights, runtime.coverage, at)
                    kwargs = {"bias_sensor_ids": biased if condition["bias"] else ()}
                    obs_seed = stable_seed(family, seed, step, condition["condition_id"], "water")
                    ov1 = observe_water(sensors_v1, at, condition["water_delay_min"], condition["water_missing_rate"], condition["water_noise_sigma"], obs_seed, **kwargs)
                    ov2 = observe_water(sensors_v2, at, condition["water_delay_min"], condition["water_missing_rate"], condition["water_noise_sigma"], obs_seed, **kwargs)
                    mv1 = map_water_sensors(ov1, mapping, runtime.edges, at, wc["mapping_full_weight"])
                    mv2 = map_water_sensors(ov2, mapping, runtime.edges, at, wc["mapping_full_weight"])
                    states = {"S0_shortest": runtime.engine.compute({"rain": mapped_rain}),
                              "S1_rain_only": runtime.engine.compute({"rain": mapped_rain}),
                              "S2_v1_redundant_naive": naive.compute({"rain": mapped_rain, "water": mv1}),
                              "S3_v2_local_naive": naive.compute({"rain": mapped_rain, "water": mv2}),
                              "S4_v2_reliability_universal": universal.compute({"rain": mapped_rain, "water": mv2}),
                              "S5_v2_reliability_source_specific": specific.compute({"rain": mapped_rain, "water": mv2})}
                    for od in ods.itertuples(index=False):
                        for method, state in states.items():
                            mode = "shortest" if method == "S0_shortest" else "risk"
                            key = (method, rain_delay, od.od_id)
                            if method in {"S0_shortest", "S1_rain_only"} and key in cache: route = cache[key]
                            else:
                                route = runtime.plan(state, request(od, at, mode)); cache[key] = route
                            rows.append(record(route, state, truth_state, lengths, cfg, {"scenario_family": family, "seed": seed,
                                "decision_step": step, "timestamp": at, "od_id": od.od_id, "condition_id": condition["condition_id"],
                                "method": method, **{k: condition[k] for k in condition}}))
            print(f"Confirmatory main: {family} seed {seed}", flush=True)
    return pd.DataFrame(rows), pd.DataFrame(latent_rows), pd.concat(patch_rows, ignore_index=True)


def summarize(routes, cfg):
    formal = routes[routes.method.isin(METHODS)].copy()
    metrics = ["truth_exposure", "distance_m", "max_truth_risk", "p95_truth_risk", "high_risk_length_ratio",
               "rain_effective_weight_mean", "water_effective_weight_mean", "water_effective_weight_p90", "fallback_fraction",
               "low_reliability_water_usage", "source_disagreement_fraction"]
    seed_summary = formal.groupby(["scenario_family", "seed", "method"], as_index=False)[metrics].mean()
    perfect = routes[routes.method.eq("S6_perfect_water_v2")].groupby(["scenario_family", "seed", "method"], as_index=False)[metrics].mean()
    seed_summary = pd.concat([seed_summary, perfect], ignore_index=True)
    family_summary = seed_summary.groupby(["scenario_family", "method"], as_index=False).agg(
        truth_exposure_mean=("truth_exposure", "mean"), truth_exposure_sd=("truth_exposure", "std"),
        distance_m_mean=("distance_m", "mean"), water_effective_weight_mean=("water_effective_weight_mean", "mean"),
        fallback_fraction=("fallback_fraction", "mean"))
    wide = seed_summary.pivot(index=["scenario_family", "seed"], columns="method", values="truth_exposure")
    specs = [(m + "-minus-rain", m, "S1_rain_only") for m in METHODS[2:] + ["S6_perfect_water_v2"]]
    specs += [("reliability-minus-naive", "S5_v2_reliability_source_specific", "S3_v2_local_naive"),
              ("source_specific-minus-universal", "S5_v2_reliability_source_specific", "S4_v2_reliability_universal")]
    comparisons = pd.DataFrame([{"scenario_family": family, "seed": seed, "comparison": name,
        "mean_difference": float(row[left] - row[right])} for (family, seed), row in wide.iterrows() for name, left, right in specs])
    rng = np.random.default_rng(cfg["experiment"]["bootstrap_seed"]); seeds = np.array(cfg["experiment"]["seeds"]); boot = []
    for family in [*cfg["experiment"]["scenario_families"], "all_families"]:
        subset = comparisons if family == "all_families" else comparisons[comparisons.scenario_family.eq(family)]
        for name, group in subset.groupby("comparison"):
            by_seed = group.groupby("seed").mean_difference.mean().reindex(seeds)
            samples = np.array([by_seed.loc[rng.choice(seeds, len(seeds), replace=True)].mean() for _ in range(cfg["experiment"]["bootstrap_iterations"])])
            boot.append({"scenario_family": family, "comparison": name, "mean_difference": float(by_seed.mean()),
                         "ci_low": float(np.quantile(samples, .025)), "ci_high": float(np.quantile(samples, .975)),
                         "bootstrap_unit": "seed", "iterations": len(samples), "bootstrap_seed": cfg["experiment"]["bootstrap_seed"]})
    return seed_summary, family_summary, comparisons, pd.DataFrame(boot)


def failure_cases(routes, cfg):
    formal = routes[routes.method.isin(METHODS)]; key = ["scenario_family", "seed", "od_id", "decision_step", "condition_id"]
    wide = formal.pivot(index=key, columns="method", values="truth_exposure"); rows = []
    for index, row in wide.iterrows():
        common = dict(zip(key, index))
        if row.S5_v2_reliability_source_specific > row.S1_rain_only + .01: rows.append({**common, "failure_type": "multisource_worse_than_rain_only", "difference": row.S5_v2_reliability_source_specific-row.S1_rain_only})
        if row.S5_v2_reliability_source_specific > row.S3_v2_local_naive + .01: rows.append({**common, "failure_type": "trusted_worse_than_naive", "difference": row.S5_v2_reliability_source_specific-row.S3_v2_local_naive})
        if common["condition_id"] == "C04_water_missing" and abs(row.S5_v2_reliability_source_specific-row.S1_rain_only) > 1e-9: rows.append({**common, "failure_type": "missing_source_failed_to_fallback", "difference": row.S5_v2_reliability_source_specific-row.S1_rain_only})
        if common["condition_id"] in {"C03_water_stale", "C06_asynchronous"} and row.S5_v2_reliability_source_specific > row.S1_rain_only + .01: rows.append({**common, "failure_type": "stale_source_induced_bad_route", "difference": row.S5_v2_reliability_source_specific-row.S1_rain_only})
    weights = formal[formal.method.eq("S5_v2_reliability_source_specific")].set_index(key).water_effective_weight_mean
    clean_key = weights.reset_index(); clean_key = clean_key[clean_key.condition_id.eq("C00_clean")].set_index(key[:-1]).water_effective_weight_mean
    for index, value in weights.items():
        base = clean_key.loc[index[:-1]]
        if index[-1] in {"C02_degraded", "C03_water_stale", "C07_disagreement"} and value > base + 1e-12: rows.append({**dict(zip(key,index)), "failure_type":"bad_source_overweighted", "difference":value-base})
        if index[-1] == "C00_clean" and value <= 1e-9: rows.append({**dict(zip(key,index)), "failure_type":"fresh_source_underweighted", "difference":value})
    return pd.DataFrame(rows)


class Planner:
    def __init__(self, runtime, cfg): self.edges=runtime.edges; self.router=runtime.router; self.config=cfg; self.cfg=cfg
    def plan(self, state, req): return self.router.plan_frame(req, state, self.cfg["routing"])


def trigger_study(runtime, cfg, grids, sensors, mapping, ods):
    ex=cfg["experiment"]; wc=cfg["synthetic_water"]; spec=ex["trigger"]; engine=ReliabilityWeightedRiskEngine(runtime.edges,cfg,"source_specific")
    planner=Planner(runtime,cfg); lengths=runtime.edges.set_index(EDGE).length_m; chosen=ods[ods.od_id.isin(spec["od_ids"])]
    summary, detail, failures=[],[],[]; east=set(sensors.nlargest(len(sensors)//2,"lon").sensor_id); biased=set(sensors.sort_values("sensor_id").head(16).sensor_id)
    for family in ex["scenario_families"]:
      for seed in spec["seeds"]:
        truth=generate_family_truth(grids,runtime.edges.total_bounds,family,seed,cfg["scenario"]["start"]); raw,norm=rain_frames(runtime,truth,cfg["sources"]["rain"]["scale"])
        water,_=simulate_latent_ponding_v2(runtime.edges,norm,family,seed,cfg["water_v2"]["local_field_seed"],wc["integration_step_min"],wc["inflow_gain"])
        stable=sensor_truth_table(sensors,engine.index,water,wc["sensor_cadence_min"],tuple(wc["sensor_group_offsets_min"])); times=[pd.Timestamp(x) for x in sorted(truth.timestamp.unique())]
        for case in spec["stress_cases"]:
          for od in chosen.itertuples(index=False):
            controllers={p:ReplayController(planner,p) for p in spec["policies"]}; records={p:[] for p in controllers}
            for step,at in enumerate(times):
                rain_delay=60 if case=="rain_stale_water_fresh" else 0
                water_delay=60 if case=="water_stale_rain_fresh" else (min(60,step*10) if case=="water_gradually_stale" else 0)
                rain=map_rainfall(observe(truth,at,rain_delay,0,0,stable_seed(family,seed,case,step,"rain")),runtime.weights,runtime.coverage,at)
                kwargs={}
                if case in {"water_block_outage","water_recovery"}: kwargs={"outage_sensor_ids":east,"outage_start":times[3],"outage_end":times[5] if case=="water_recovery" else times[-1]}
                if case=="sources_disagreement": kwargs["bias_sensor_ids"]=biased
                obs=observe_water(stable,at,water_delay,.2,.05,stable_seed(family,seed,case,step,"water"),**kwargs)
                mapped=map_water_sensors(obs,mapping,runtime.edges,at,wc["mapping_full_weight"]); state=engine.compute({"rain":rain,"water":mapped})
                truth_state=build_truth_state(engine,norm[at],water[at],ex["truth_weights"])
                for policy,controller in controllers.items():
                    before=controller.current_route; before_value=None if before is None else truth_metrics(before,truth_state,lengths,cfg["routing"]["high_risk"])["truth_exposure"]
                    log=controller.step(state,request(od,at,"trusted")); metrics=truth_metrics(controller.current_route,truth_state,lengths,cfg["routing"]["high_risk"])
                    item={"scenario_family":family,"seed":seed,"stress_case":case,"od_id":od.od_id,"step":step,"timestamp":at,"policy":policy,**log,**metrics,
                          "route_digest":route_digest(controller.current_route.edge_ids),"unnecessary_replan":bool(log["route_changed"] and before_value is not None and metrics["truth_exposure"]>=before_value)}
                    records[policy].append(item); detail.append(item)
            always=pd.DataFrame(records["always"]).truth_exposure.mean()
            for policy,data in records.items():
                f=pd.DataFrame(data); seq=f.route_digest.tolist(); oscillation=any(seq[i]==seq[i-2]!=seq[i-1] for i in range(2,len(seq))); mean=float(f.truth_exposure.mean())
                row={"scenario_family":family,"seed":seed,"stress_case":case,"od_id":od.od_id,"policy":policy,"mean_truth_exposure":mean,
                     "planner_calls":int(f.planner_calls.iloc[-1]),"route_change_count":int(f.route_change_count.iloc[-1]),"missed_useful_replan":bool(policy=="triggered" and mean>always+.01),
                     "unnecessary_replan":bool(f.unnecessary_replan.any()),"route_oscillation":bool(oscillation)}; summary.append(row)
                for flag in ["missed_useful_replan","unnecessary_replan","route_oscillation"]:
                    if row[flag]: failures.append({**{k:row[k] for k in ["scenario_family","seed","stress_case","od_id","policy"]},"failure_type":flag,"difference":mean-always})
        print(f"Trigger V2: {family} seed {seed}",flush=True)
    return pd.DataFrame(summary),pd.DataFrame(detail),pd.DataFrame(failures)


def stable_hash(frame):
    data=frame.drop(columns=[c for c in frame if c.endswith("_ms")],errors="ignore").copy().reindex(sorted(frame.columns),axis=1)
    for c in data.select_dtypes(include=["datetime","datetimetz"]): data[c]=pd.to_datetime(data[c],utc=True).astype(str)
    if len(data): data=data.sort_values(list(data.columns),kind="mergesort",na_position="first").reset_index(drop=True)
    return hashlib.sha256(data.to_csv(index=False,lineterminator="\n",float_format="%.12g").encode()).hexdigest()


def save_figures(out,routes,trigger,sensors):
    plt.rcParams.update({"font.sans-serif":["Microsoft YaHei","SimHei","DejaVu Sans"],"axes.unicode_minus":False}); d=out/"figures";d.mkdir(exist_ok=True)
    formal=routes[routes.method.isin(METHODS)]; labels={"S0_shortest":"最短路","S1_rain_only":"仅降雨","S2_v1_redundant_naive":"V1冗余源","S3_v2_local_naive":"V2朴素多源","S4_v2_reliability_universal":"V2统一时效","S5_v2_reliability_source_specific":"V2分源时效"}
    def bar(table,title,name,y="平均真值风险暴露"):
        fig,ax=plt.subplots(figsize=(8,4.5));table.plot(kind="bar",ax=ax,color="#0072B2");ax.set(title=title,ylabel=y,xlabel="");ax.tick_params(axis="x",rotation=18);fig.tight_layout();fig.savefig(d/name,dpi=180);plt.close(fig)
    clean=formal[formal.condition_id.eq("C00_clean")].groupby("method").truth_exposure.mean().reindex(labels);clean.index=[labels[x] for x in clean.index];bar(clean,"Clean Water 多源收益","Clean Water 多源收益.png")
    delay=formal[formal.method.eq("S5_v2_reliability_source_specific")].groupby("water_delay_min").water_effective_weight_mean.mean();bar(delay,"Water 延迟与有效贡献","Water 延迟与有效贡献.png","Water 平均有效权重")
    missing=formal[formal.method.isin(["S1_rain_only","S5_v2_reliability_source_specific"])].groupby(["water_missing_rate","method"]).truth_exposure.mean().unstack();fig,ax=plt.subplots(figsize=(7,4.5));missing.plot(ax=ax,marker="o");ax.set(title="Water 缺失与安全退化",ylabel="平均真值风险暴露",xlabel="缺失率");fig.tight_layout();fig.savefig(d/"Water 缺失与安全退化.png",dpi=180);plt.close(fig)
    for condition,title,name in [("C05_rain_stale","Rain陈旧 Water新鲜 权重变化","Rain陈旧_Water新鲜_权重变化.png"),("C03_water_stale","Water陈旧 Rain新鲜 权重变化","Water陈旧_Rain新鲜_权重变化.png")]:
        x=formal[(formal.condition_id==condition)&(formal.method=="S5_v2_reliability_source_specific")][["rain_effective_weight_mean","water_effective_weight_mean"]].mean();x.index=["Rain","Water"];bar(x,title,name,"平均有效权重")
    means=formal.groupby("method").truth_exposure.mean().reindex(labels);means.index=[labels[x] for x in means.index];bar(means,"多源方法风险暴露比较","多源方法风险暴露比较.png")
    t=trigger.groupby(["stress_case","policy"]).mean_truth_exposure.mean().unstack();fig,ax=plt.subplots(figsize=(10,4.8));t.plot(kind="bar",ax=ax);ax.set(title="Trigger 多源动态回放",ylabel="平均真值风险暴露");ax.tick_params(axis="x",rotation=25);fig.tight_layout();fig.savefig(d/"Trigger 多源动态回放.png",dpi=180);plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,5));p=ax.scatter(sensors.lon,sensors.lat,c=sensors.static_susceptibility,cmap="viridis",edgecolors="black",s=35);ax.set(title="多源传感器地图（受控模拟）",xlabel="经度",ylabel="纬度");fig.colorbar(p,label="静态易涝度");fig.tight_layout();fig.savefig(d/"多源传感器地图.png",dpi=180);plt.close(fig)


def environment():
    if sha256(FROZEN)!=EXPECTED_FROZEN_SHA: raise RuntimeError("Frozen config changed")
    cfg=load_config(CONFIG); protocol=json.loads(PROTOCOL.read_text(encoding="utf-8")); runtime=Runtime(load_config(FROZEN)); grids=grid_polygons(ROOT/cfg["grids_path"])
    ods=pd.read_csv(ROOT/cfg["experiment"]["od_source"]); sensors=select_sensors(runtime.router.edges,cfg["synthetic_water"]["sensor_selection_seed"]); mapping=build_sensor_edge_mapping(runtime.edges,sensors,cfg["synthetic_water"]["mapping_radius_m"],cfg["synthetic_water"]["mapping_scale_m"])
    return cfg,protocol,runtime,grids,ods,sensors,mapping


def run_part(out, seeds):
    cfg,protocol,runtime,grids,ods,sensors,mapping=environment(); cfg=copy.deepcopy(cfg); cfg["experiment"]["seeds"]=[int(x) for x in seeds]
    out.mkdir(parents=True,exist_ok=True); routes,latent,patches=evaluate(runtime,cfg,protocol,grids,sensors,mapping,ods)
    routes.to_parquet(out/"routes.parquet",index=False);latent.to_parquet(out/"latent.parquet",index=False);patches.to_parquet(out/"patches.parquet",index=False)
    write_json(out/"part_manifest.json",{"seeds":cfg["experiment"]["seeds"],"route_count":len(routes),"route_hash":stable_hash(routes),"latent_hash":stable_hash(latent),"patch_hash":stable_hash(patches)})


def run_trigger_part(out, seeds):
    cfg,protocol,runtime,grids,ods,sensors,mapping=environment(); cfg=copy.deepcopy(cfg); cfg["experiment"]["trigger"]["seeds"]=[int(x) for x in seeds]
    out.mkdir(parents=True,exist_ok=True); summary,detail,failures=trigger_study(runtime,cfg,grids,sensors,mapping,ods)
    summary.to_parquet(out/"trigger_summary.parquet",index=False); detail.to_parquet(out/"trigger_detail.parquet",index=False); failures.to_parquet(out/"trigger_failures.parquet",index=False)
    write_json(out/"trigger_manifest.json",{"seeds":seeds,"summary_hash":stable_hash(summary),"detail_hash":stable_hash(detail),"failure_hash":stable_hash(failures)})


def finalize(out, routes, latent, patches, trigger_data=None):
    cfg,protocol,runtime,grids,ods,sensors,mapping=environment(); out.mkdir(parents=True,exist_ok=True); seed,family,comparisons,bootstrap=summarize(routes,cfg)
    if trigger_data is None: trigger,trigger_detail,trigger_fail=trigger_study(runtime,cfg,grids,sensors,mapping,ods)
    else: trigger,trigger_detail,trigger_fail=trigger_data
    failures=pd.concat([failure_cases(routes,cfg),trigger_fail],ignore_index=True,sort=False)
    registry=pd.DataFrame(sensors.drop(columns="_point")); mechanism=routes[routes.method.isin(METHODS)].groupby(["condition_id","method"],as_index=False)[["rain_effective_weight_mean","water_effective_weight_mean","water_effective_weight_p90","fallback_fraction","low_reliability_water_usage","source_disagreement_fraction","truth_exposure"]].mean()
    files={"routes.parquet":routes,"latent_state_summary.csv":latent,"disturbance_patches.csv":patches,"sensor_registry.csv":registry,"seed_summary.csv":seed,"family_summary.csv":family,"method_comparisons.csv":comparisons,"bootstrap_ci.csv":bootstrap,"mechanism_metrics.csv":mechanism,"trigger_summary.csv":trigger,"trigger_detail.parquet":trigger_detail,"failure_cases.csv":failures}
    hashes={}
    for name,frame in files.items():
        path=out/name; frame.to_parquet(path,index=False) if path.suffix==".parquet" else frame.to_csv(path,index=False); hashes[name]=stable_hash(frame)
    write_json(out/"config_snapshot.json",cfg);(out/"config_sha256.txt").write_text(sha256(CONFIG)+"\n",encoding="utf-8")
    write_json(out/"run_manifest.json",{"protocol_commit":"59da81f","route_count":len(routes),"formal_route_count":int(routes.method.isin(METHODS).sum()),"perfect_reference_count":int(routes.method.eq("S6_perfect_water_v2").sum()),"trigger_summary_count":len(trigger),"failure_count":len(failures),"stable_output_hashes":hashes})
    save_figures(out,routes,trigger,registry); print(json.dumps(json.loads((out/"run_manifest.json").read_text()),ensure_ascii=False,indent=2))


def run(out):
    cfg,protocol,runtime,grids,ods,sensors,mapping=environment(); out.mkdir(parents=True,exist_ok=True)
    routes,latent,patches=evaluate(runtime,cfg,protocol,grids,sensors,mapping,ods); finalize(out,routes,latent,patches)


def assemble(out, parts, trigger_parts=None):
    routes=pd.concat([pd.read_parquet(Path(p)/"routes.parquet") for p in parts],ignore_index=True)
    latent=pd.concat([pd.read_parquet(Path(p)/"latent.parquet") for p in parts],ignore_index=True)
    patches=pd.concat([pd.read_parquet(Path(p)/"patches.parquet") for p in parts],ignore_index=True)
    trigger_data=None
    if trigger_parts:
        trigger_data=(pd.concat([pd.read_parquet(Path(p)/"trigger_summary.parquet") for p in trigger_parts],ignore_index=True),
                      pd.concat([pd.read_parquet(Path(p)/"trigger_detail.parquet") for p in trigger_parts],ignore_index=True),
                      pd.concat([pd.read_parquet(Path(p)/"trigger_failures.parquet") for p in trigger_parts],ignore_index=True))
    finalize(out,routes,latent,patches,trigger_data)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,default=ROOT/"results/multisource_fusion_v2")
    parser.add_argument("--part-seeds",nargs="+",type=int);parser.add_argument("--assemble-parts",nargs="+",type=Path)
    parser.add_argument("--trigger-part-seeds",nargs="+",type=int);parser.add_argument("--trigger-parts",nargs="+",type=Path)
    args=parser.parse_args()
    if args.part_seeds: run_part(args.output,args.part_seeds)
    elif args.trigger_part_seeds: run_trigger_part(args.output,args.trigger_part_seeds)
    elif args.assemble_parts: assemble(args.output,args.assemble_parts,args.trigger_parts)
    else: run(args.output)
