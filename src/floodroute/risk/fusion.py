"""Experiment-only reliability-weighted dynamic fusion.

The strategy consumes observed source frames only.  It has no import or API for
latent truth, route results, OD selection, or observation error.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .freshness import freshness
from .static import static_components


class ReliabilityWeightedRiskEngine:
    """Fuse dynamic sources by continuous freshness and observable reliability."""

    def __init__(self, edges, config, tau_policy="source_specific"):
        if tau_policy not in {"source_specific", "universal"}:
            raise ValueError("Unknown tau policy")
        self.config = config; self.tau_policy = tau_policy
        self.index = pd.MultiIndex.from_frame(edges[["u", "v", "key"]])
        self.static, self.static_unknown = static_components(edges, config)

    def compute(self, observed_sources):
        cfg = self.config; fusion = cfg["fusion_v2"]
        numer = np.zeros(len(self.index), dtype=float); denom = np.zeros(len(self.index), dtype=float)
        output = pd.DataFrame({"static_risk": self.static, "static_missing_fraction": self.static_unknown}, index=self.index)
        source_confidences = []
        for name in fusion["sources"]:
            settings = cfg["sources"][name]
            frame = observed_sources.get(name, pd.DataFrame()).reindex(self.index)
            def column(key, default):
                return frame[key].to_numpy(float) if key in frame else np.full(len(self.index), default, dtype=float)
            values = column("value", np.nan)
            coverage = np.nan_to_num(column("coverage", 0), nan=0).clip(0, 1)
            quality = np.nan_to_num(column("quality", 1), nan=1).clip(0, 1)
            age = column("age_min", np.nan)
            available = np.isfinite(values) & (coverage > 0)
            tau = fusion["universal_tau_min"] if self.tau_policy == "universal" else settings["tau_min"]
            fresh = freshness(age, tau)
            # Mapping coverage is already used to construct the local sensor
            # estimate.  A square-root transform preserves continuous
            # downweighting without applying a second linear penalty to the
            # intentionally sparse 48-sensor network.
            reliability = np.sqrt(coverage) * (1 - quality)
            effective = fusion["base_weights"][name] * fresh * reliability * available
            normalized_value = np.nan_to_num(values / settings["scale"], nan=0).clip(0, 1)
            numer += effective * normalized_value; denom += effective
            source_confidences.append(fresh * reliability * available)
            output[f"{name}_freshness"] = fresh
            output[f"{name}_reliability"] = reliability
            output[f"{name}_availability"] = available.astype(float)
            output[f"{name}_effective_weight"] = effective
            output[f"{name}_age_min"] = age
            output[f"{name}_coverage"] = coverage
        fallback = denom <= fusion["fallback_epsilon"]
        dynamic = np.divide(numer, denom, out=np.zeros_like(numer), where=~fallback)
        static_weight = cfg["static"]["weight"]; dynamic_weight = fusion["dynamic_weight"]
        risk = np.where(
            fallback, self.static,
            (static_weight * self.static + dynamic_weight * dynamic) / (static_weight + dynamic_weight),
        ).clip(0, 1)
        confidence = np.mean(source_confidences, axis=0) if source_confidences else np.zeros(len(risk))
        uncertainty = np.clip(1 - confidence + cfg["uncertainty"]["static_missing"] * self.static_unknown, 0, 1)
        output["dynamic_risk"] = dynamic; output["effective_weight_sum"] = denom
        output["fallback_static_only"] = fallback.astype(float)
        output["risk"] = risk; output["risk_uncertainty"] = risk
        output["trusted_risk"] = risk; output["confidence"] = confidence
        output["freshness"] = np.mean([output[f"{name}_freshness"] for name in fusion["sources"]], axis=0)
        output["uncertainty"] = uncertainty
        return output

