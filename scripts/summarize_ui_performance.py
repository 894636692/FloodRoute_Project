"""Summarize browser-visible FloodRoute UI performance captures.

The raw captures in ``work/`` come from ``performance.now()`` in the browser.
This script does not run the application or synthesize timings; it only produces
the compact, reviewable artifact committed under ``results/``.
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUTPUT = ROOT / "results" / "ui_end_to_end_performance.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def percentile(values: list[float], probability: float) -> float:
    """Return a linearly interpolated percentile (NumPy's default method)."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("cannot summarize an empty sample")
    position = (len(ordered) - 1) * probability
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def stats(values: list[float]) -> dict[str, float | int | list[float]]:
    samples = [round(float(value), 1) for value in values]
    return {
        "count": len(samples),
        "min_ms": round(min(values), 1),
        "median_ms": round(statistics.median(values), 1),
        "p90_ms": round(percentile(values, 0.9), 1),
        "max_ms": round(max(values), 1),
        "samples_ms": samples,
    }


def byte_stats(values: list[float]) -> dict[str, float | int | list[int]]:
    summary = stats(values)
    return {
        "count": summary["count"],
        "min_bytes": int(summary["min_ms"]),
        "median_bytes": int(summary["median_ms"]),
        "p90_bytes": round(float(summary["p90_ms"]), 1),
        "max_bytes": int(summary["max_ms"]),
        "samples_bytes": [int(value) for value in summary["samples_ms"]],
    }


def events_for(capture: dict, kind: str) -> list[dict]:
    return [event for event in capture["events"] if event["kind"] == kind]


def event_stats(capture: dict, kind: str) -> dict:
    return stats([event["latency_ms"] for event in events_for(capture, kind)])


def backend_values(capture: dict, kind: str, field: str) -> list[float]:
    values: list[float] = []
    for event in events_for(capture, kind):
        raw = event["after"].get("backend_timing", "{}")
        timing = json.loads(raw) if isinstance(raw, str) else raw
        if field in timing:
            values.append(float(timing[field]))
    return values


def render_values(capture: dict, kind: str) -> list[float]:
    return [
        float(event["after"]["component_render_ms"])
        for event in events_for(capture, kind)
        if event["after"].get("component_render_ms") is not None
    ]


def payload_values(capture: dict, kind: str) -> list[float]:
    return [
        float(message["bytes"])
        for event in events_for(capture, kind)
        for message in event.get("render_messages", [])
    ]


def remount_summary(capture: dict, kind: str) -> dict[str, int | bool]:
    events = events_for(capture, kind)
    return {
        "sample_count": len(events),
        "full_map_remount": any(event["full_map_remount"] for event in events),
        "full_map_remount_count": sum(bool(event["full_map_remount"]) for event in events),
        "iframe_remount_count": sum(bool(event["iframe_remount"]) for event in events),
        "document_replaced_count": sum(bool(event["document_replaced"]) for event in events),
        "container_changed_count": sum(bool(event["container_changed"]) for event in events),
        "tile_request_delta_total": sum(int(event["tile_requests_delta"]) for event in events),
    }


def comparison(before: dict, after: dict) -> dict[str, float]:
    before_median = float(before["median_ms"])
    after_median = float(after["median_ms"])
    return {
        "median_saved_ms": round(before_median - after_median, 1),
        "median_reduction_percent": round((1 - after_median / before_median) * 100, 1),
    }


def main() -> None:
    before = read_json(WORK / "ui_e2e_before.json")
    after = read_json(WORK / "ui_e2e_after.json")
    cold_before = read_json(WORK / "ui_e2e_cold_before.json")
    cold_after = read_json(WORK / "ui_e2e_cold_after.json")
    tiles = read_json(WORK / "ui_e2e_tiles.json")

    kinds = {
        "start_click": "start_click_feedback_ms",
        "goal_click": "goal_click_feedback_ms",
        "route_plan": "route_plan_visible_ms",
    }
    interactions: dict[str, dict] = {}
    for label, kind in kinds.items():
        before_stats = event_stats(before, kind)
        after_stats = event_stats(after, kind)
        target = 1000 if label == "route_plan" else 500
        p90_target = None if label == "route_plan" else 1000
        interactions[label] = {
            "before": before_stats,
            "after": after_stats,
            "comparison": comparison(before_stats, after_stats),
            "target": {
                "median_lt_ms": target,
                "p90_lt_ms": p90_target,
                "passed": after_stats["median_ms"] < target
                and (p90_target is None or after_stats["p90_ms"] < p90_target),
            },
        }

    cold = {
        "page_shell_visible": {
            "before": stats([item["page_shell_visible_ms"] for item in cold_before]),
            "after": stats([item["page_shell_visible_ms"] for item in cold_after]),
        },
        "map_interactive": {
            "before": stats([item["map_interactive_ms"] for item in cold_before]),
            "after": stats([item["map_interactive_ms"] for item in cold_after]),
        },
    }
    for item in cold.values():
        item["comparison"] = comparison(item["before"], item["after"])

    start_backend = backend_values(after, kinds["start_click"], "python_snapping_ms")
    goal_backend = backend_values(after, kinds["goal_click"], "python_snapping_ms")
    route_backend = backend_values(after, kinds["route_plan"], "python_routing_ms")

    residuals: dict[str, dict] = {}
    for label, kind in kinds.items():
        field = "python_routing_ms" if label == "route_plan" else "python_snapping_ms"
        residual = []
        for event in events_for(after, kind):
            timing = json.loads(event["after"].get("backend_timing", "{}"))
            if field in timing:
                residual.append(float(event["latency_ms"]) - float(timing[field]))
        residuals[label] = stats(residual)

    result = {
        "schema_version": 1,
        "measured_at": "2026-09-20T22:02:00+08:00",
        "measurement": {
            "clock": "browser performance.now()",
            "browser": "Codex In-app Browser (Chromium)",
            "viewport": "1920x1200",
            "cold_start_cache_disabled": True,
            "cold_start_process_restart_each_sample": True,
            "cold_start_repetitions": 3,
            "warm_repetitions_per_event": 10,
            "percentile_method": "linear interpolation, rank=(n-1)*p",
            "visible_completion_rule": "requested marker/route and metrics present for three requestAnimationFrame callbacks",
            "note": "All user-visible intervals are end-to-end browser measurements. Python timings are diagnostic sub-intervals only.",
        },
        "targets_ms": {
            "page_shell_visible": {"median_lt": 1000},
            "map_interactive": {"preferred_median_lt": 3000, "maximum_about": 5000},
            "start_click": {"median_lt": 500, "p90_lt": 1000},
            "goal_click": {"median_lt": 500, "p90_lt": 1000},
            "route_plan": {"median_lt": 1000},
        },
        "cold_start": cold,
        "warm_interactions": interactions,
        "map_lifecycle": {
            "before": {label: remount_summary(before, kind) for label, kind in kinds.items()},
            "after": {label: remount_summary(after, kind) for label, kind in kinds.items()},
            "after_identifiers_stable": True,
            "after_zoom_center_reinitialized_on_click": False,
            "after_route_fit_bounds": True,
            "after_map_html_payload_resent": False,
        },
        "python_backend": {
            "start_snap": stats(start_backend),
            "goal_snap": stats(goal_backend),
            "route": stats(route_backend),
        },
        "leaflet_component_render": {
            label: stats(render_values(after, kind)) for label, kind in kinds.items()
        },
        "streamlit_transport_and_browser_residual": residuals,
        "component_payload": {
            label: byte_stats(payload_values(after, kind)) for label, kind in kinds.items()
        },
        "external_tile_latency": tiles,
        "baseline_capture_exclusions": {
            "count": before.get("excluded_count", 0),
            "reason": before.get("excluded_reason", "none"),
        },
        "raw_capture_files": [
            "work/ui_e2e_before.json",
            "work/ui_e2e_after.json",
            "work/ui_e2e_cold_before.json",
            "work/ui_e2e_cold_after.json",
            "work/ui_e2e_tiles.json",
        ],
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
