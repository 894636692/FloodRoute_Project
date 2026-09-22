import hashlib
import json
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

from floodroute.experiments.synthetic_water import (
    EDGE, SOURCE_KIND, build_sensor_edge_mapping, drainage_tau, map_water_sensors,
    observe_water, sensor_truth_table, simulate_latent_ponding,
    static_susceptibility,
)
from floodroute.risk.freshness import freshness
from floodroute.risk.trusted import RiskEngine


ROOT = Path(__file__).resolve().parents[1]


def edges_frame(n=3):
    return gpd.GeoDataFrame({
        "u": range(n), "v": range(1, n + 1), "key": 0,
        "low_elev_norm": np.linspace(.1, .9, n), "flatness_risk": np.linspace(.1, .9, n),
        "builtup_frac": np.linspace(.1, .9, n), "vegetation_frac": np.linspace(.9, .1, n),
        "water_frac": .1, "dem_valid_frac": 1., "slope_valid_frac": 1.,
        "worldcover_valid_frac": 1., "quality_flag": "valid", "length_m": 100.,
    }, geometry=[LineString([(i * 20., 0.), (i * 20. + 10., 0.)]) for i in range(n)], crs="EPSG:32650")


def config(water_active=True, water_tau=20):
    cfg = json.loads((ROOT / "config/multisource_synthetic_water.json").read_text(encoding="utf-8"))
    cfg["sources"]["water"]["active"] = water_active
    cfg["sources"]["water"]["tau_min"] = water_tau
    return cfg


class SyntheticWaterTests(unittest.TestCase):
    def setUp(self):
        self.edges = edges_frame()
        self.index = pd.MultiIndex.from_frame(self.edges[EDGE])
        self.times = pd.date_range("2023-09-07T12:00:00+08:00", periods=5, freq="15min")

    def rain_states(self, values):
        return {t: pd.DataFrame({"value": value}, index=self.index) for t, value in zip(self.times, values)}

    def sensors(self):
        points = self.edges.geometry.interpolate(.5, normalized=True)
        display = gpd.GeoSeries(points, crs=self.edges.crs).to_crs(4326)
        return gpd.GeoDataFrame({
            "sensor_id": ["S001", "S002", "S003"], "u": self.edges.u, "v": self.edges.v,
            "key": 0, "lon": display.x, "lat": display.y, "sensor_group": [0, 1, 2],
        }, geometry=points, crs=self.edges.crs)

    def test_01_latent_bounds(self):
        states = simulate_latent_ponding(self.edges, self.rain_states([.2, .7, 1., .2, 0.]))
        self.assertTrue(all(((x >= 0) & (x <= 1)).all() for x in states.values()))

    def test_02_no_rain_does_not_grow(self):
        states = simulate_latent_ponding(self.edges, self.rain_states([0., 0., 0., 0., 0.]))
        self.assertEqual(max(float(x.max()) for x in states.values()), 0.)

    def test_03_water_does_not_instantly_zero_after_rain(self):
        states = simulate_latent_ponding(self.edges, self.rain_states([1., 1., 0., 0., 0.]))
        values = [states[t][2] for t in sorted(states)]
        self.assertGreater(values[-1], 0)
        self.assertLess(values[-1], max(values))

    def test_04_same_inputs_reproduce(self):
        first = simulate_latent_ponding(self.edges, self.rain_states([.1, .3, .8, .2, 0.]))
        second = simulate_latent_ponding(self.edges, self.rain_states([.1, .3, .8, .2, 0.]))
        for timestamp in first:
            np.testing.assert_array_equal(first[timestamp], second[timestamp])

    def test_05_different_observation_seeds_differ(self):
        states = simulate_latent_ponding(self.edges, self.rain_states([.1, .3, .8, .2, 0.]))
        truth = sensor_truth_table(self.sensors(), self.index, states)
        a = observe_water(truth, self.times[-1], 0, 0, .15, 1)
        b = observe_water(truth, self.times[-1], 0, 0, .15, 2)
        self.assertFalse(a.water_level_index.equals(b.water_level_index))

    def test_06_susceptible_edge_responds_more(self):
        states = simulate_latent_ponding(self.edges, self.rain_states([1., 1., 1., 1., 1.]))
        self.assertGreater(states[max(states)][-1], states[max(states)][0])

    def test_07_truth_and_observation_columns_are_separate(self):
        states = simulate_latent_ponding(self.edges, self.rain_states([.1, .3, .8, .2, 0.]))
        truth = sensor_truth_table(self.sensors(), self.index, states)
        observed = observe_water(truth, self.times[-1], 0, 0, 0, 1)
        self.assertIn("latent_ponding_truth", truth)
        self.assertNotIn("latent_ponding_truth", observed)

    def test_08_planner_source_kind_is_explicitly_synthetic(self):
        states = simulate_latent_ponding(self.edges, self.rain_states([.1, .3, .8, .2, 0.]))
        truth = sensor_truth_table(self.sensors(), self.index, states)
        observed = observe_water(truth, self.times[-1], 0, 0, 0, 1)
        self.assertEqual(set(observed.source_kind), {SOURCE_KIND})
        self.assertFalse(observed.astype(str).apply(lambda c: c.str.contains("REAL|真实水位").any()).any())

    def test_09_future_retrieved_at_is_invisible(self):
        states = simulate_latent_ponding(self.edges, self.rain_states([.1, .3, .8, .2, 0.]))
        truth = sensor_truth_table(self.sensors(), self.index, states)
        observed = observe_water(truth, self.times[1], 60, 0, 0, 1)
        mapping = build_sensor_edge_mapping(self.edges, self.sensors(), 100, 40)
        mapped = map_water_sensors(observed, mapping, self.edges, self.times[1], 1.5)
        self.assertTrue(mapped.value.isna().all())
        self.assertTrue(mapped.coverage.fillna(0).eq(0).all())

    def test_10_missing_does_not_become_zero(self):
        states = simulate_latent_ponding(self.edges, self.rain_states([.1, .3, .8, .2, 0.]))
        truth = sensor_truth_table(self.sensors(), self.index, states)
        observed = observe_water(truth, self.times[-1], 0, 1, 0, 1)
        mapping = build_sensor_edge_mapping(self.edges, self.sensors(), 100, 40)
        mapped = map_water_sensors(observed, mapping, self.edges, self.times[-1], 1.5)
        self.assertTrue(mapped.value.isna().all())

    def test_11_inactive_water_does_not_change_risk(self):
        engine = RiskEngine(self.edges, config(False))
        rain = pd.DataFrame({"value": 20., "age_min": 0., "coverage": 1., "quality": 0.}, index=self.index)
        water = pd.DataFrame({"value": 1., "age_min": 0., "coverage": 1., "quality": 0.}, index=self.index)
        pd.testing.assert_frame_equal(engine.compute({"rain": rain}), engine.compute({"rain": rain, "water": water}))

    def test_12_production_config_water_inactive(self):
        for name in ["final_v1.json", "selected_v1_1.json"]:
            cfg = json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))
            self.assertFalse(cfg["sources"]["water"]["active"])

    def test_13_historical_entrypoint_does_not_load_synthetic_config(self):
        text = (ROOT / "scripts/run_historical_validation.py").read_text(encoding="utf-8")
        self.assertNotIn("multisource_synthetic_water", text)

    def test_14_only_experiment_config_activates_water(self):
        cfg = config(True)
        self.assertTrue(cfg["experiment_only"])
        self.assertEqual(cfg["source_kind"], SOURCE_KIND)

    def test_15_water_cadence_differs_from_rain(self):
        cfg = config(True)
        self.assertEqual(cfg["synthetic_water"]["sensor_cadence_min"], 10)
        self.assertEqual(cfg["scenario"]["step_min"], 15)

    def test_16_freshness_monotonically_decreases(self):
        values = freshness(np.array([0., 10., 30., 60.]), 20)
        self.assertTrue(np.all(np.diff(values) < 0))

    def test_17_source_specific_tau_is_applied(self):
        cfg = config(True, 20)
        engine = RiskEngine(self.edges, cfg)
        rain = pd.DataFrame({"value": 20., "age_min": 20., "coverage": 1., "quality": 0.}, index=self.index)
        water = pd.DataFrame({"value": .5, "age_min": 20., "coverage": 1., "quality": 0.}, index=self.index)
        state = engine.compute({"rain": rain, "water": water})
        self.assertAlmostEqual(state.rain_freshness.iloc[0], np.exp(-20 / 60))
        self.assertAlmostEqual(state.water_freshness.iloc[0], np.exp(-1))

    def test_18_uncertainty_responds_to_coverage_and_quality(self):
        engine = RiskEngine(self.edges, config(True))
        rain = pd.DataFrame({"value": 20., "age_min": 0., "coverage": 1., "quality": 0.}, index=self.index)
        good = pd.DataFrame({"value": .5, "age_min": 0., "coverage": 1., "quality": 0.}, index=self.index)
        bad = pd.DataFrame({"value": .5, "age_min": 0., "coverage": .2, "quality": 1.}, index=self.index)
        self.assertTrue((engine.compute({"rain": rain, "water": bad}).uncertainty > engine.compute({"rain": rain, "water": good}).uncertainty).all())

    def test_19_observation_seed_reproduces_exactly(self):
        states = simulate_latent_ponding(self.edges, self.rain_states([.1, .3, .8, .2, 0.]))
        truth = sensor_truth_table(self.sensors(), self.index, states)
        a = observe_water(truth, self.times[-1], 10, .2, .05, 77)
        b = observe_water(truth, self.times[-1], 10, .2, .05, 77)
        pd.testing.assert_frame_equal(a, b)

    def test_20_frozen_hash_and_no_truth_leakage_import(self):
        raw = (ROOT / "config/selected_v1_1.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "3f8ea08239d12d19b801afec28b5156625dd08daef4f54ff72573756bd7e6dd5")
        runtime_text = (ROOT / "src/floodroute/runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("latent_ponding_truth", runtime_text)


if __name__ == "__main__":
    unittest.main()
