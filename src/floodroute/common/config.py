"""Centralized B-module parameters.

All risk, freshness, uncertainty, routing, and trigger constants live here so
experiments can record and reproduce the exact parameter set.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class StaticRiskWeights:
    low_elevation: float = 0.42
    flatness: float = 0.24
    builtup: float = 0.22
    water: float = 0.10
    vegetation_relief: float = 0.02


@dataclass(frozen=True)
class DynamicRiskWeights:
    static: float = 0.62
    rain: float = 0.20
    water: float = 0.18


@dataclass(frozen=True)
class FreshnessConfig:
    rain_tau_min: float = 45.0
    water_tau_min: float = 20.0
    forecast_tau_min: float = 90.0


@dataclass(frozen=True)
class UncertaintyConfig:
    base: float = 0.08
    distance_scale_m: float = 900.0
    bad_quality_penalty: float = 0.25
    missing_penalty: float = 0.35
    ensemble_std_scale: float = 20.0


@dataclass(frozen=True)
class TrustedRiskConfig:
    uncertainty_weight: float = 0.55
    rain_staleness_weight: float = 0.24
    water_staleness_weight: float = 0.36


@dataclass(frozen=True)
class RoutingConfig:
    shortest_cost: str = "length_m"
    risk_alpha: float = 4.0
    trusted_alpha: float = 4.8
    default_speed_mps: float = 8.0
    output_crs: str = "EPSG:4326"


@dataclass(frozen=True)
class TriggerConfig:
    min_confidence: float = 0.55
    max_mean_trusted_risk_increase: float = 0.08
    max_high_risk_edge_ratio: float = 0.22
    high_trusted_risk: float = 0.78
    min_replan_interval_min: float = 10.0
    route_change_jaccard_threshold: float = 0.35


@dataclass(frozen=True)
class ExperimentConfig:
    delays_min: tuple[int, ...] = (0, 15, 30, 60, 120)
    missing_rates: tuple[float, ...] = (0.0, 0.2, 0.4)
    noise_levels: tuple[float, ...] = (0.0, 0.1, 0.2)


@dataclass(frozen=True)
class FloodRouteConfig:
    calculation_crs: str = "EPSG:32650"
    schema_version: str = "b-routing-v1"
    static_weights: StaticRiskWeights = StaticRiskWeights()
    dynamic_weights: DynamicRiskWeights = DynamicRiskWeights()
    freshness: FreshnessConfig = FreshnessConfig()
    uncertainty: UncertaintyConfig = UncertaintyConfig()
    trusted: TrustedRiskConfig = TrustedRiskConfig()
    routing: RoutingConfig = RoutingConfig()
    trigger: TriggerConfig = TriggerConfig()
    experiment: ExperimentConfig = ExperimentConfig()

    def to_dict(self) -> dict:
        return asdict(self)

