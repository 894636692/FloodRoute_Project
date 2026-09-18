"""Scenario experiment for delay and trigger metrics."""

from __future__ import annotations

import csv
from pathlib import Path

from floodroute.common.schema import RouteRequest
from floodroute.routing.service import RoutePlanningService
from floodroute.routing.trigger import TriggerPolicy


def run_delay_experiment(
    static_features_path: str | Path,
    request: RouteRequest,
    rainfall_csv_by_delay: dict[int, str],
    water_csv_by_delay: dict[int, str],
    output_csv: str | Path,
) -> list[dict]:
    """Run delay scenarios without exposing Ground Truth to planning."""

    policy = TriggerPolicy()
    rows = []
    current_route = None
    last_replan_at = None
    replan_count = 0
    route_change_count = 0
    for delay in sorted(rainfall_csv_by_delay):
        service = RoutePlanningService(
            static_features_path,
            rainfall_csv=rainfall_csv_by_delay[delay],
            water_level_csv=water_csv_by_delay.get(delay),
        )
        candidate = service.plan(request)
        decision = policy.decide(current_route, candidate, request.timestamp, last_replan_at)
        if decision.triggered:
            replan_count += 1
            if decision.route_change:
                route_change_count += 1
            current_route = candidate
            last_replan_at = request.timestamp

        rows.append(
            {
                "delay_min": delay,
                "distance_m": round(candidate.distance_m, 2),
                "mean_risk": round(candidate.mean_risk, 4),
                "max_risk": round(candidate.max_risk, 4),
                "confidence": round(candidate.confidence, 4),
                "triggered": decision.triggered,
                "trigger_reason": decision.reason,
                "route_change": decision.route_change,
                "replan_count": replan_count,
                "route_change_count": route_change_count,
            }
        )

    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    with Path(output_csv).open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows

