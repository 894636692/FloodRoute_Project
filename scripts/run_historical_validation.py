"""Replay the 2023-09-07/08 event with the frozen v1.2.0 model.

Impact labels enter only after every road risk has been computed.  They are
offline weak labels and are never passed to Runtime, RiskEngine, or routing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from floodroute.runtime import Runtime, write_json


EVENT_DIR = ROOT / "data/historical/shenzhen_2023_0907"
OUTPUT_DIR = ROOT / "results/historical_validation"
FIGURE_DIR = OUTPUT_DIR / "figures"
CONFIG_PATH = ROOT / "config/selected_v1_1.json"
EVENT_START = pd.Timestamp("2023-09-07T18:00:00+08:00")
EVENT_END = pd.Timestamp("2023-09-08T19:00:00+08:00")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configure_chinese_font() -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def load_inputs() -> tuple[Runtime, pd.DataFrame, pd.DataFrame]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    runtime = Runtime(config)
    forcing = pd.read_parquet(EVENT_DIR / "rainfall_forcing.parquet")
    forcing["timestamp"] = pd.to_datetime(forcing.timestamp, utc=True).dt.tz_convert("Asia/Shanghai")
    forcing["window_start"] = pd.to_datetime(forcing.window_start, utc=True).dt.tz_convert("Asia/Shanghai")
    forcing["grid_id"] = forcing.grid_id.astype(str)
    forcing = forcing[forcing.timestamp.between(EVENT_START, EVENT_END)].copy()
    labels = pd.read_parquet(EVENT_DIR / "impact_roads.parquet")
    labels = labels[labels.eligible_main].copy()
    return runtime, forcing, labels


def replay(runtime: Runtime, forcing: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for timestamp, observed in forcing.groupby("timestamp", sort=True):
        # Historical offline replay deliberately omits retrieved_at. POWER Final
        # forcing was obtained after the event and is not claimed as live input.
        state = runtime.observed_state(observed.drop(columns=["retrieved_at"], errors="ignore"), timestamp)
        frame = state.reset_index()
        frame.insert(0, "timestamp", timestamp)
        frames.append(frame)
        print(f"Historical risk {timestamp.isoformat()} complete", flush=True)
    return pd.concat(frames, ignore_index=True)


def select_background_edges(runtime: Runtime, labels: pd.DataFrame, count: int = 5) -> pd.DataFrame:
    """Select nearby similar roads for context, never as confirmed negatives."""
    roads = runtime.edges.copy()
    roads["static_risk"] = runtime.engine.static
    roads = roads.set_index(["u", "v", "key"], drop=False)
    selected = []
    impacted_ids = set(map(tuple, labels[["u", "v", "key"]].astype(int).to_numpy()))
    for label in labels.itertuples():
        edge_id = (int(label.u), int(label.v), int(label.key))
        target = roads.loc[edge_id]
        distances = roads.geometry.distance(target.geometry.centroid)
        length_ratio = roads.length_m / float(target.length_m)
        candidates = roads[
            roads.highway.astype(str).eq(str(target.highway))
            & distances.le(3000)
            & length_ratio.between(0.5, 2.0)
            & (roads.static_risk - float(target.static_risk)).abs().le(0.10)
        ].copy()
        candidates["distance_to_impacted_m"] = distances.loc[candidates.index]
        candidates["static_risk_difference"] = (candidates.static_risk - float(target.static_risk)).abs()
        candidates["length_ratio_difference"] = (np.log(candidates.length_m / float(target.length_m))).abs()
        candidates = candidates[
            [tuple(map(int, idx)) not in impacted_ids for idx in candidates.index]
        ].reset_index(drop=True)
        candidates["match_score"] = (
            candidates.distance_to_impacted_m / 3000
            + candidates.static_risk_difference / 0.10
            + candidates.length_ratio_difference
        )
        candidates = candidates.sort_values(["match_score", "u", "v", "key"]).head(count)
        for rank, row in enumerate(candidates.itertuples(), start=1):
            selected.append({
                "report_id": label.report_id,
                "background_rank": rank,
                "u": int(row.u), "v": int(row.v), "key": int(row.key),
                "highway": row.highway, "length_m": float(row.length_m),
                "static_risk": float(row.static_risk),
                "distance_to_impacted_m": float(row.distance_to_impacted_m),
                "match_score": float(row.match_score),
                "role": "matched_background_not_confirmed_safe",
            })
    return pd.DataFrame(selected)


def score_labels(risks: pd.DataFrame, labels: pd.DataFrame, backgrounds: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows = []
    risks = risks.copy()
    risks["risk_percentile"] = risks.groupby("timestamp")["risk"].rank(method="average", pct=True) * 100
    for label in labels.itertuples():
        start = pd.Timestamp(label.event_time_start)
        end = pd.Timestamp(label.event_time_end)
        edge = risks[
            risks.u.eq(label.u) & risks.v.eq(label.v) & risks.key.eq(label.key)
        ].copy()
        window = edge[edge.timestamp.between(start, end)]
        if window.empty:
            continue
        for record in window.itertuples():
            rows.append({
                "report_id": label.report_id, "role": "reported_impacted",
                "u": int(label.u), "v": int(label.v), "key": int(label.key),
                "timestamp": record.timestamp, "risk": float(record.risk),
                "trusted_risk": float(record.trusted_risk),
                "risk_percentile": float(record.risk_percentile),
                "time_window_uncertainty": "reported interval; exact onset within road segment unknown",
            })
        for bg in backgrounds[backgrounds.report_id.eq(label.report_id)].itertuples():
            bg_edge = risks[
                risks.u.eq(bg.u) & risks.v.eq(bg.v) & risks.key.eq(bg.key)
                & risks.timestamp.between(start, end)
            ]
            for record in bg_edge.itertuples():
                rows.append({
                    "report_id": label.report_id, "role": "matched_background_not_confirmed_safe",
                    "u": int(bg.u), "v": int(bg.v), "key": int(bg.key),
                    "timestamp": record.timestamp, "risk": float(record.risk),
                    "trusted_risk": float(record.trusted_risk),
                    "risk_percentile": float(record.risk_percentile),
                    "time_window_uncertainty": "same evaluation window as reported road",
                })
    scores = pd.DataFrame(rows)
    impacted = scores[scores.role.eq("reported_impacted")]
    report_summary = impacted.groupby("report_id").agg(
        mean_risk=("risk", "mean"), max_risk=("risk", "max"),
        median_risk_percentile=("risk_percentile", "median"),
        max_risk_percentile=("risk_percentile", "max"),
        evaluated_timestamps=("timestamp", "nunique"),
    ).reset_index()
    for top in (5, 10, 20):
        report_summary[f"covered_top_{top}_percent"] = report_summary.max_risk_percentile.ge(100 - top)
    bg = scores[scores.role.ne("reported_impacted")]
    comparison = None
    if not impacted.empty and not bg.empty:
        comparison = {
            "reported_mean_risk": float(impacted.risk.mean()),
            "matched_background_mean_risk": float(bg.risk.mean()),
            "mean_difference": float(impacted.risk.mean() - bg.risk.mean()),
            "background_interpretation": "comparison only; not confirmed safe roads",
        }
    summary = {
        "eligible_report_count": int(report_summary.report_id.nunique()),
        "eligible_directed_edge_count": int(labels[["u", "v", "key"]].drop_duplicates().shape[0]),
        "median_reported_risk_percentile": (
            float(report_summary.median_risk_percentile.median()) if not report_summary.empty else None
        ),
        "coverage_at_top_k": {
            str(top): float(report_summary[f"covered_top_{top}_percent"].mean()) if not report_summary.empty else None
            for top in (5, 10, 20)
        },
        "matched_background_edge_count": int(len(backgrounds)),
        "matched_background_comparison": comparison,
        "no_confirmed_negative_roads": True,
    }
    return scores.merge(report_summary, on="report_id", how="left"), summary


def plot_outputs(runtime: Runtime, forcing: pd.DataFrame, risks: pd.DataFrame, labels: pd.DataFrame,
                 scores: pd.DataFrame, summary: dict) -> None:
    configure_chinese_font()
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    note = "灾情位置来源于公开报道，属于事件级弱标签。"
    hourly = forcing.groupby("timestamp", as_index=False).rain_mm.first()
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(hourly.timestamp, hourly.rain_mm, marker="o", linewidth=1.8)
    ax.set(title="历史事件区域粗分辨率降雨过程", xlabel="北京时间", ylabel="NASA POWER 小时降雨（毫米）")
    ax.grid(alpha=.25); fig.autofmt_xdate(); fig.text(.5, .01, "区域级 MERRA-2 强迫，不代表道路实测雨量。", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .04, 1, 1)); fig.savefig(FIGURE_DIR / "历史事件降雨过程.png", dpi=180); plt.close(fig)

    peak_time = hourly.loc[hourly.rain_mm.idxmax(), "timestamp"]
    peak = risks[risks.timestamp.eq(peak_time)].set_index(["u", "v", "key"])
    roads = runtime.edges.copy(); roads["risk"] = peak.reindex(pd.MultiIndex.from_frame(roads[["u", "v", "key"]])).risk.to_numpy()
    fig, ax = plt.subplots(figsize=(11, 7))
    roads.plot(ax=ax, column="risk", cmap="YlOrRd", norm=Normalize(0, 1), linewidth=.25, rasterized=True, legend=True)
    if not labels.empty:
        selected = roads.set_index(["u", "v", "key"]).loc[
            [tuple(x) for x in labels[["u", "v", "key"]].astype(int).to_numpy()]
        ]
        selected.plot(ax=ax, color="#1261a0", linewidth=3, label="公开报道受影响道路")
        ax.legend()
    ax.set_title(f"历史事件道路风险地图（{peak_time.strftime('%Y-%m-%d %H:%M')}）")
    ax.set_axis_off(); fig.text(.5, .01, note, ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .03, 1, 1)); fig.savefig(FIGURE_DIR / "历史事件道路风险地图.png", dpi=180); plt.close(fig)

    impacted = scores[scores.role.eq("reported_impacted")]
    fig, ax = plt.subplots(figsize=(9, 5))
    if impacted.empty:
        ax.text(.5, .5, "没有符合主阈值的可定位样本", ha="center", va="center")
    else:
        for report_id, group in impacted.groupby("report_id"):
            ax.plot(group.timestamp, group.risk_percentile, marker="o", label=report_id)
        ax.axhspan(95, 100, color="#d73027", alpha=.10, label="全路网风险前5%")
        ax.legend()
    ax.set(title="已报道受影响道路风险百分位", xlabel="北京时间", ylabel="风险百分位（%）", ylim=(0, 100))
    ax.grid(alpha=.25); fig.autofmt_xdate(); fig.text(.5, .01, note, ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .04, 1, 1)); fig.savefig(FIGURE_DIR / "已报道受影响道路风险百分位.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5))
    top = [5, 10, 20]; values = [summary["coverage_at_top_k"][str(x)] for x in top]
    ax.bar([f"前{x}%" for x in top], [0 if v is None else 100*v for v in values], color="#2c7fb8")
    ax.set(title="高风险道路覆盖已报道灾情位置", xlabel="全路网风险排序阈值", ylabel="弱标签覆盖率（%）", ylim=(0, 100))
    fig.text(.5, .01, note, ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .04, 1, 1)); fig.savefig(FIGURE_DIR / "高风险道路覆盖已报道灾情位置.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5))
    groups = [
        impacted.risk.to_numpy(),
        scores[scores.role.ne("reported_impacted")].risk.to_numpy(),
    ]
    if all(len(x) for x in groups):
        ax.boxplot(groups, tick_labels=["已报道受影响道路", "匹配背景道路"])
    else:
        ax.text(.5, .5, "匹配背景样本不足", ha="center", va="center")
    ax.set(title="灾情道路与匹配背景道路风险分布", ylabel="冻结模型风险指数")
    fig.text(.5, .01, note + " 背景道路不是确认安全道路。", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .05, 1, 1)); fig.savefig(FIGURE_DIR / "灾情道路与匹配背景道路风险分布.png", dpi=180); plt.close(fig)


def main() -> None:
    runtime, forcing, labels = load_inputs()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    risks = replay(runtime, forcing)
    risk_path = OUTPUT_DIR / "road_risk_timeseries.parquet"
    risks.to_parquet(risk_path, index=False, compression="zstd")
    backgrounds = select_background_edges(runtime, labels)
    backgrounds.to_csv(OUTPUT_DIR / "matched_background_roads.csv", index=False, encoding="utf-8")
    scores, metrics = score_labels(risks, labels, backgrounds)
    scores.to_csv(OUTPUT_DIR / "impact_road_scores.csv", index=False, encoding="utf-8")
    rainfall_hourly = forcing.groupby("timestamp", as_index=False).rain_mm.first()
    summary = {
        "status": "completed_with_sparse_weak_labels",
        "interpretation": "offline external ordering check under real coarse historical forcing",
        "forcing_data_type": "REAL_HISTORICAL_COARSE_FORCING",
        "forcing_is_road_observation": False,
        "risk_rows": int(len(risks)),
        "road_count": int(risks[["u", "v", "key"]].drop_duplicates().shape[0]),
        "timestamp_count": int(risks.timestamp.nunique()),
        "event_rain_total_mm_at_power_point": float(rainfall_hourly.rain_mm.sum()),
        "event_rain_peak_hourly_mm_at_power_point": float(rainfall_hourly.rain_mm.max()),
        "frozen_config_sha256": sha256(CONFIG_PATH),
        "water_source_active": bool(runtime.config["sources"]["water"]["active"]),
        **metrics,
        "limitations": [
            "NASA POWER forcing is coarse MERRA-2 data and under-resolves the official Shenzhen extremes.",
            "Only one reported road segment is both auditable and inside the formal network.",
            "Unreported roads are not confirmed negatives.",
            "No road water depth observations are available.",
        ],
    }
    write_json(OUTPUT_DIR / "summary.json", summary)
    manifest = {
        "event_id": "shenzhen_2023_0907",
        "release_basis": {"tag": "v1.2.0", "commit": "0f4f9a2b5e83a9ec0f051a6826731e749d356434"},
        "frozen_config": "config/selected_v1_1.json",
        "frozen_config_sha256": sha256(CONFIG_PATH),
        "event_window": {"start": EVENT_START.isoformat(), "end": EVENT_END.isoformat()},
        "inputs": {
            "source_manifest": {"path": "data/historical/shenzhen_2023_0907/source_manifest.json", "sha256": sha256(EVENT_DIR / "source_manifest.json")},
            "rainfall_forcing": {"path": "data/historical/shenzhen_2023_0907/rainfall_forcing.parquet", "sha256": sha256(EVENT_DIR / "rainfall_forcing.parquet")},
            "impact_reports": {"path": "data/historical/shenzhen_2023_0907/impact_reports.csv", "sha256": sha256(EVENT_DIR / "impact_reports.csv")},
            "impact_roads": {"path": "data/historical/shenzhen_2023_0907/impact_roads.parquet", "sha256": sha256(EVENT_DIR / "impact_roads.parquet")},
        },
        "label_use": "offline evaluation only; never planner, risk, trigger, interpolation, or parameter input",
        "main_match_threshold_m": 100,
        "output_rows": {"road_risk_timeseries": int(len(risks)), "impact_road_scores": int(len(scores))},
    }
    write_json(OUTPUT_DIR / "event_manifest.json", manifest)
    plot_outputs(runtime, forcing, risks, labels, scores, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
