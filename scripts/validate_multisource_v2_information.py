"""Validate information gain in synthetic water V2 before routing experiments.

The analysis is descriptive and uses the preregistered development seeds.  It
does not use OD pairs, routes, planner outcomes, or tune any threshold.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from floodroute.experiments.expanded import generate_family_truth
from floodroute.experiments.scenario import observe
from floodroute.experiments.synthetic_water import simulate_latent_ponding, static_susceptibility
from floodroute.experiments.synthetic_water_v2 import simulate_latent_ponding_v2
from floodroute.gis.grid_mapping import grid_polygons
from floodroute.risk.dynamic import map_rainfall
from floodroute.runtime import Runtime, load_config, write_json

CONFIG = ROOT / "config/multisource_fusion_v2_development.json"
OUT = ROOT / "results/multisource_fusion_v2/information_gain"
RAIN_BINS = np.linspace(0, 1, 11)
STATIC_BINS = np.linspace(0, 1, 6)
LOW_RAIN, HIGH_WATER = .25, .50


def spearman(x, y):
    return float(pd.Series(x).rank(method="average").corr(pd.Series(y).rank(method="average")))


def rain_frames(runtime, truth, scale):
    result = {}
    for timestamp in sorted(truth.timestamp.unique()):
        at = pd.Timestamp(timestamp)
        frame = map_rainfall(observe(truth, at, seed=0), runtime.weights, runtime.coverage, at)
        frame["value"] = (frame.value / scale).clip(0, 1)
        result[at] = frame
    return result


class Accumulator:
    def __init__(self):
        self.n = np.zeros((10, 5), dtype=np.int64)
        self.total = np.zeros((10, 5)); self.square = np.zeros((10, 5))
        self.hist = np.zeros((10, 100), dtype=np.int64)
        self.high_low = 0; self.all = 0

    def add(self, rain, static, water):
        rb = np.clip(np.digitize(rain, RAIN_BINS[1:-1]), 0, 9)
        sb = np.clip(np.digitize(static, STATIC_BINS[1:-1]), 0, 4)
        self.high_low += int(((rain <= LOW_RAIN) & (water >= HIGH_WATER)).sum())
        self.all += len(water)
        for r in range(10):
            mask_r = rb == r
            self.hist[r] += np.histogram(water[mask_r], np.linspace(0, 1, 101))[0]
            for s in range(5):
                values = water[mask_r & (sb == s)]
                self.n[r, s] += len(values); self.total[r, s] += values.sum()
                self.square[r, s] += np.square(values).sum()

    def table(self, version):
        rows = []
        for r in range(10):
            for s in range(5):
                n = int(self.n[r, s]); mean = self.total[r, s] / n if n else np.nan
                variance = max(0., self.square[r, s] / n - mean**2) if n else np.nan
                rows.append({"generator": version, "rain_bin": r, "static_bin": s,
                             "count": n, "water_mean": mean, "conditional_water_variance": variance})
        return pd.DataFrame(rows)

    def bin_table(self, version):
        rows = []
        edges = np.linspace(0, 1, 101); centers = (edges[:-1] + edges[1:]) / 2
        for r in range(10):
            counts = self.hist[r]; n = int(counts.sum())
            values = np.repeat(centers, counts)
            rows.append({"generator": version, "rain_bin": r, "rain_low": RAIN_BINS[r],
                         "rain_high": RAIN_BINS[r + 1], "count": n,
                         "water_mean": float(values.mean()) if n else np.nan,
                         "water_std": float(values.std()) if n else np.nan,
                         "water_p10": float(np.quantile(values, .1)) if n else np.nan,
                         "water_p50": float(np.quantile(values, .5)) if n else np.nan,
                         "water_p90": float(np.quantile(values, .9)) if n else np.nan})
        return pd.DataFrame(rows)


def weighted_variance(table):
    valid = table.dropna(subset=["conditional_water_variance"])
    return float(np.average(valid.conditional_water_variance, weights=valid["count"]))


def save_figures(correlations, conditional, bins, sample_edges, sample):
    plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
                         "axes.unicode_minus": False})
    figdir = OUT / "figures"; figdir.mkdir(parents=True, exist_ok=True)
    means = correlations.groupby("generator")[["pearson", "spearman"]].mean().reindex(["V1_redundant", "V2_local_state"])
    ax = means.plot(kind="bar", figsize=(7.4, 4.4), color=["#0072B2", "#E69F00"])
    ax.set(title="V1 与 V2 Water 信息冗余对比", ylabel="相关系数", xlabel="模拟水源生成器", ylim=(0, 1))
    ax.legend(["Pearson", "Spearman"]); ax.tick_params(axis="x", rotation=0)
    ax.figure.tight_layout(); ax.figure.savefig(figdir / "V1 与 V2 Water 信息冗余对比.png", dpi=180); plt.close(ax.figure)

    view = bins[bins.generator.eq("V2_local_state")]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.fill_between(view.rain_bin, view.water_p10, view.water_p90, alpha=.25, color="#0072B2", label="P10–P90")
    ax.plot(view.rain_bin, view.water_p50, marker="o", color="#0072B2", label="中位数")
    ax.set(title="同降雨条件下局部积涝状态差异", xlabel="降雨风险分箱（低→高）", ylabel="模拟积涝状态指数")
    ax.legend(); fig.tight_layout(); fig.savefig(figdir / "同降雨条件下局部积涝状态差异.png", dpi=180); plt.close(fig)

    frame = sample_edges.copy(); frame["water_residual"] = sample["residual"]
    # Deterministic thinning keeps the delivered raster compact without filtering by outcome.
    plotted = frame.iloc[::max(1, len(frame) // 30000)].copy()
    limit = float(np.quantile(np.abs(plotted.water_residual), .98)) or .01
    fig, ax = plt.subplots(figsize=(8.3, 6.2))
    plotted.plot(column="water_residual", ax=ax, cmap="RdBu_r", vmin=-limit, vmax=limit,
                 linewidth=.45, legend=True, legend_kwds={"label": "Water residual"})
    ax.set(title="Rain 与 Water 独立信息示例（受控模拟 residual）"); ax.set_axis_off()
    fig.tight_layout(); fig.savefig(figdir / "Rain 与 Water 独立信息示例.png", dpi=180); plt.close(fig)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config(CONFIG); runtime = Runtime(load_config(ROOT / "config/selected_v1_1.json"))
    grids = grid_polygons(ROOT / cfg["grids_path"]); static = static_susceptibility(runtime.edges)
    accumulators = {"V1_redundant": Accumulator(), "V2_local_state": Accumulator()}
    correlations = []; latent_rows = []; patch_rows = []; sample = None
    for family in cfg["development"]["scenario_families"]:
        for seed in cfg["development"]["seeds"]:
            truth = generate_family_truth(grids, runtime.edges.total_bounds, family, seed, cfg["scenario"]["start"])
            rain = rain_frames(runtime, truth, cfg["sources"]["rain"]["scale"])
            v1 = simulate_latent_ponding(runtime.edges, rain, cfg["synthetic_water"]["integration_step_min"], cfg["synthetic_water"]["inflow_gain"])
            v2, meta = simulate_latent_ponding_v2(runtime.edges, rain, family, seed,
                cfg["water_v2"]["local_field_seed"], cfg["synthetic_water"]["integration_step_min"],
                cfg["synthetic_water"]["inflow_gain"])
            local = meta["local_hydrologic_state"]
            latent_rows.append({"scenario_family": family, "seed": seed, "local_min": local.min(),
                                "local_mean": local.mean(), "local_max": local.max(),
                                "patch_count": len(meta["patches"])})
            p = meta["patches"].copy(); p["scenario_family"] = family; p["seed"] = seed; patch_rows.append(p)
            for name, states in [("V1_redundant", v1), ("V2_local_state", v2)]:
                rx, wy = [], []
                for at in sorted(rain):
                    x = rain[at].value.fillna(0).to_numpy(float); y = states[at].astype(float)
                    accumulators[name].add(x, static, y); rx.append(x); wy.append(y)
                x = np.concatenate(rx); y = np.concatenate(wy)
                correlations.append({"generator": name, "scenario_family": family, "seed": seed,
                                     "n": len(x), "pearson": float(np.corrcoef(x, y)[0, 1]),
                                     "spearman": spearman(x, y)})
            if family == cfg["development"]["scenario_families"][0] and seed == cfg["development"]["seeds"][0]:
                at = sorted(rain)[cfg["development"]["decision_step"]]
                sample = {"rain": rain[at].value.fillna(0).to_numpy(float), "static": static,
                          "water": v2[at].astype(float), "local": local, "timestamp": at}
            print(f"Information gain: {family} seed {seed}", flush=True)

    correlations = pd.DataFrame(correlations)
    conditional = pd.concat([a.table(name) for name, a in accumulators.items()], ignore_index=True)
    bins = pd.concat([a.bin_table(name) for name, a in accumulators.items()], ignore_index=True)
    correlations.to_csv(OUT / "rain_water_correlations.csv", index=False)
    conditional.to_csv(OUT / "conditional_water_variance.csv", index=False)
    bins.to_csv(OUT / "water_by_rain_bin.csv", index=False)
    pd.DataFrame(latent_rows).to_csv(OUT / "latent_local_state_summary.csv", index=False)
    pd.concat(patch_rows, ignore_index=True).to_csv(OUT / "disturbance_patches.csv", index=False)

    rb = np.clip(np.digitize(sample["rain"], RAIN_BINS[1:-1]), 0, 9)
    sb = np.clip(np.digitize(sample["static"], STATIC_BINS[1:-1]), 0, 4)
    lookup = conditional[conditional.generator.eq("V2_local_state")].set_index(["rain_bin", "static_bin"]).water_mean
    expected = np.array([lookup.loc[(r, s)] for r, s in zip(rb, sb)])
    sample["residual"] = sample["water"] - expected
    residual = runtime.edges[["u", "v", "key"]].copy()
    for key in ("rain", "static", "water", "local", "residual"): residual[key] = sample[key]
    residual.nlargest(500, "residual").to_csv(OUT / "water_residual_top500.csv", index=False)
    save_figures(correlations, conditional, bins, runtime.edges, sample)

    summary = {"analysis_type": "PRE_ROUTING_INFORMATION_GAIN", "development_seeds_only": True,
               "thresholds_fixed_before_analysis": {"low_rain_max": LOW_RAIN, "high_water_min": HIGH_WATER},
               "sample_timestamp": pd.Timestamp(sample["timestamp"]).isoformat(), "generators": {}}
    for name, acc in accumulators.items():
        corr = correlations[correlations.generator.eq(name)]
        table = conditional[conditional.generator.eq(name)]
        summary["generators"][name] = {
            "scenario_weighted_pearson": float(np.average(corr.pearson, weights=corr.n)),
            "scenario_weighted_spearman": float(np.average(corr.spearman, weights=corr.n)),
            "conditional_water_variance": weighted_variance(table),
            "high_water_low_rain_count": int(acc.high_low),
            "high_water_low_rain_ratio": float(acc.high_low / acc.all),
            "edge_time_count": int(acc.all)}
    summary["v2_information_gain_observed"] = bool(
        summary["generators"]["V2_local_state"]["conditional_water_variance"] >
        summary["generators"]["V1_redundant"]["conditional_water_variance"] and
        np.std(sample["residual"]) > 0)
    write_json(OUT / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__": run()
