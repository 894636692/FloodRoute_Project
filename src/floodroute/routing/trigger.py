"""Trigger-style replanning logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from floodroute.common.config import FloodRouteConfig
from floodroute.common.schema import parse_iso8601
from floodroute.routing.router import PlannedRoute


@dataclass
class TriggerDecision:
    triggered: bool
    reason: str
    route_change: bool


class TriggerPolicy:
    def __init__(self, config: FloodRouteConfig | None = None) -> None:
        self.config = config or FloodRouteConfig()

    def decide(
        self,
        current_route: PlannedRoute | None,
        candidate_route: PlannedRoute,
        timestamp: str,
        last_replan_at: str | None = None,
    ) -> TriggerDecision:
        if current_route is None:
            return TriggerDecision(True, "no_current_route", True)

        cfg = self.config.trigger
        if last_replan_at is not None:
            elapsed_min = (parse_iso8601(timestamp) - parse_iso8601(last_replan_at)).total_seconds() / 60.0
            if elapsed_min < cfg.min_replan_interval_min:
                return TriggerDecision(False, "within_min_replan_interval", False)

        if current_route.confidence < cfg.min_confidence:
            return self._with_change(current_route, candidate_route, "current_route_confidence_below_threshold")

        mean_increase = candidate_route.mean_risk - current_route.mean_risk
        if mean_increase <= -cfg.max_mean_trusted_risk_increase:
            return self._with_change(current_route, candidate_route, "candidate_route_significantly_safer")

        high_count = sum(1 for risk in current_route.edge_risks if risk >= cfg.high_trusted_risk)
        if current_route.edge_risks and high_count / len(current_route.edge_risks) > cfg.max_high_risk_edge_ratio:
            return self._with_change(current_route, candidate_route, "too_many_high_risk_edges")

        return TriggerDecision(False, "keep_current_route", False)

    def _with_change(
        self,
        current_route: PlannedRoute,
        candidate_route: PlannedRoute,
        reason: str,
    ) -> TriggerDecision:
        current_edges = set(current_route.edge_ids)
        candidate_edges = set(candidate_route.edge_ids)
        union = current_edges | candidate_edges
        overlap = len(current_edges & candidate_edges) / len(union) if union else 1.0
        changed = overlap < self.config.trigger.route_change_jaccard_threshold
        return TriggerDecision(True, reason, changed)
