import inspect
import json
from pathlib import Path
import unittest

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from floodroute.experiments.synthetic_water import (map_water_sensors, observe_water,
    sensor_truth_table)
from floodroute.experiments.synthetic_water_v2 import (event_disturbance,
    local_hydrologic_state, simulate_latent_ponding_v2)
from floodroute.risk.fusion import ReliabilityWeightedRiskEngine

ROOT = Path(__file__).resolve().parents[1]


def edges_fixture():
    rows = []
    for i in range(12):
        x, y = (i % 4) * 100., (i // 4) * 100.
        rows.append({"u": i, "v": i + 1, "key": 0, "low_elev_norm": i / 11,
                     "flatness_risk": .2 + .05 * (i % 3), "builtup_frac": .4,
                     "water_frac": .05, "vegetation_frac": .3,
                     "dem_valid_frac": 1., "slope_valid_frac": 1.,
                     "worldcover_valid_frac": 1., "quality_flag": "valid",
                     "geometry": LineString([(x, y), (x + 75, y + 30)])})
    return gpd.GeoDataFrame(rows, crs=32650)


def fusion_config():
    return {"static": {"weight": .45, "missing_prior": .5, "low_elev_norm": .42,
                       "flatness_risk": .24, "builtup_frac": .22, "water_frac": .1,
                       "vegetation_relief": .02},
            "uncertainty": {"static_missing": .3},
            "sources": {"rain": {"tau_min": 60, "scale": 1.},
                        "water": {"tau_min": 20, "scale": 1.}},
            "fusion_v2": {"sources": ["rain", "water"], "base_weights": {"rain": 1., "water": 3.},
                          "universal_tau_min": 60, "dynamic_weight": .55,
                          "fallback_epsilon": 1e-9}}


def source_frame(index, value=.5, age=0., coverage=1., quality=0.):
    return pd.DataFrame({"value": value, "age_min": age, "coverage": coverage,
                         "quality": quality}, index=index)


class MultisourceFusionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edges = edges_fixture()
        cls.index = pd.MultiIndex.from_frame(cls.edges[["u", "v", "key"]])
        cls.times = pd.date_range("2023-09-07 12:00+08:00", periods=5, freq="15min")

    def rain_states(self, values=(.2, .8, 1., .2, 0.)):
        return {t: pd.DataFrame({"value": np.full(len(self.index), v)}, index=self.index)
                for t, v in zip(self.times, values)}

    def test_01_local_field_deterministic(self):
        np.testing.assert_array_equal(local_hydrologic_state(self.edges, 9401), local_hydrologic_state(self.edges, 9401))

    def test_02_local_field_different_seed(self):
        self.assertFalse(np.array_equal(local_hydrologic_state(self.edges, 1), local_hydrologic_state(self.edges, 2)))

    def test_03_local_field_bounded(self):
        h = local_hydrologic_state(self.edges); self.assertGreaterEqual(h.min(), 0); self.assertLessEqual(h.max(), 1)

    def test_04_local_field_spatial_not_white_noise(self):
        h = local_hydrologic_state(self.edges)
        self.assertGreater(np.corrcoef(h[:-1], h[1:])[0, 1], -0.8)

    def test_05_local_field_api_has_no_route(self):
        self.assertNotIn("route", inspect.signature(local_hydrologic_state).parameters)

    def test_06_disturbance_api_has_no_od(self):
        self.assertNotIn("od", inspect.signature(event_disturbance).parameters)

    def test_07_disturbance_deterministic(self):
        a, p = event_disturbance(self.edges, "moving_center", 1, self.times)
        b, q = event_disturbance(self.edges, "moving_center", 1, self.times)
        np.testing.assert_array_equal(a[self.times[2]], b[self.times[2]]); pd.testing.assert_frame_equal(p, q)

    def test_08_disturbance_different_seed(self):
        _, a = event_disturbance(self.edges, "moving_center", 1, self.times)
        _, b = event_disturbance(self.edges, "moving_center", 2, self.times)
        self.assertFalse(a.equals(b))

    def test_09_v2_reproducible(self):
        a, _ = simulate_latent_ponding_v2(self.edges, self.rain_states(), "moving_center", 1)
        b, _ = simulate_latent_ponding_v2(self.edges, self.rain_states(), "moving_center", 1)
        np.testing.assert_array_equal(a[self.times[-1]], b[self.times[-1]])

    def test_10_v2_different_event_seed(self):
        a, _ = simulate_latent_ponding_v2(self.edges, self.rain_states(), "moving_center", 1)
        b, _ = simulate_latent_ponding_v2(self.edges, self.rain_states(), "moving_center", 2)
        self.assertFalse(np.array_equal(a[self.times[-1]], b[self.times[-1]]))

    def test_11_water_bounded(self):
        states, _ = simulate_latent_ponding_v2(self.edges, self.rain_states(), "moving_center", 1)
        self.assertTrue(all((x.min() >= 0 and x.max() <= 1) for x in states.values()))

    def test_12_water_decays_after_rain_stops(self):
        states, _ = simulate_latent_ponding_v2(self.edges, self.rain_states((1, 1, 0, 0, 0)), "moving_center", 1)
        self.assertLess(states[self.times[-1]].mean(), states[self.times[2]].mean())

    def test_13_conditionally_independent_variation(self):
        states, meta = simulate_latent_ponding_v2(self.edges, self.rain_states((.5,) * 5), "moving_center", 1)
        self.assertGreater(np.var(states[self.times[-1]]), 0); self.assertGreater(np.var(meta["local_hydrologic_state"]), 0)

    def test_14_planner_module_does_not_import_latent_generator(self):
        from floodroute.risk import fusion
        self.assertNotIn("synthetic_water_v2", inspect.getsource(fusion))

    def test_15_fusion_compute_has_no_truth_argument(self):
        self.assertNotIn("truth", inspect.signature(ReliabilityWeightedRiskEngine.compute).parameters)

    def test_16_freshness_weight_decreases(self):
        e = ReliabilityWeightedRiskEngine(self.edges, fusion_config())
        a = e.compute({"rain": source_frame(self.index), "water": source_frame(self.index, age=0)})
        b = e.compute({"rain": source_frame(self.index), "water": source_frame(self.index, age=60)})
        self.assertTrue((b.water_effective_weight < a.water_effective_weight).all())

    def test_17_reliability_weight_decreases_with_coverage(self):
        e = ReliabilityWeightedRiskEngine(self.edges, fusion_config())
        a = e.compute({"water": source_frame(self.index, coverage=1)})
        b = e.compute({"water": source_frame(self.index, coverage=.25)})
        self.assertTrue((b.water_effective_weight < a.water_effective_weight).all())

    def test_18_reliability_weight_decreases_with_quality_penalty(self):
        e = ReliabilityWeightedRiskEngine(self.edges, fusion_config())
        a = e.compute({"water": source_frame(self.index, quality=0)})
        b = e.compute({"water": source_frame(self.index, quality=.5)})
        self.assertTrue((b.water_effective_weight < a.water_effective_weight).all())

    def test_19_missing_water_equals_rain_only(self):
        e = ReliabilityWeightedRiskEngine(self.edges, fusion_config()); rain = source_frame(self.index, .6)
        a = e.compute({"rain": rain}); b = e.compute({"rain": rain, "water": source_frame(self.index, np.nan, coverage=0)})
        np.testing.assert_allclose(a.risk, b.risk)

    def test_20_all_missing_uses_static_fallback(self):
        e = ReliabilityWeightedRiskEngine(self.edges, fusion_config()); out = e.compute({})
        self.assertTrue(out.fallback_static_only.eq(1).all()); np.testing.assert_allclose(out.risk, out.static_risk)

    def test_21_missing_is_not_zero_observation(self):
        e = ReliabilityWeightedRiskEngine(self.edges, fusion_config())
        missing = e.compute({"water": source_frame(self.index, np.nan, coverage=0)})
        zero = e.compute({"water": source_frame(self.index, 0., coverage=1)})
        self.assertTrue(missing.fallback_static_only.eq(1).all()); self.assertTrue(zero.fallback_static_only.eq(0).all())

    def test_22_rain_stale_water_fresh_increases_relative_water(self):
        e = ReliabilityWeightedRiskEngine(self.edges, fusion_config())
        clean = e.compute({"rain": source_frame(self.index, age=0), "water": source_frame(self.index, age=0)})
        stale = e.compute({"rain": source_frame(self.index, age=60), "water": source_frame(self.index, age=0)})
        self.assertGreater((stale.water_effective_weight / stale.rain_effective_weight).mean(),
                           (clean.water_effective_weight / clean.rain_effective_weight).mean())

    def test_23_water_stale_rain_fresh_decreases_relative_water(self):
        e = ReliabilityWeightedRiskEngine(self.edges, fusion_config())
        clean = e.compute({"rain": source_frame(self.index), "water": source_frame(self.index)})
        stale = e.compute({"rain": source_frame(self.index), "water": source_frame(self.index, age=60)})
        self.assertLess((stale.water_effective_weight / stale.rain_effective_weight).mean(),
                        (clean.water_effective_weight / clean.rain_effective_weight).mean())

    def test_24_low_reliability_lowers_confidence(self):
        e = ReliabilityWeightedRiskEngine(self.edges, fusion_config())
        good = e.compute({"rain": source_frame(self.index), "water": source_frame(self.index)})
        bad = e.compute({"rain": source_frame(self.index, age=200, quality=.8), "water": source_frame(self.index, age=200, quality=.8)})
        self.assertLess(bad.confidence.mean(), good.confidence.mean())

    def test_25_quality_formula_has_no_truth_error(self):
        source = inspect.getsource(ReliabilityWeightedRiskEngine.compute)
        self.assertNotIn("observed - truth", source); self.assertNotIn("truth_error", source)

    def test_26_production_water_inactive(self):
        cfg = json.loads((ROOT / "config/final_v1.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["sources"]["water"]["active"])

    def test_27_frozen_research_water_inactive(self):
        cfg = json.loads((ROOT / "config/selected_v1_1.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["sources"]["water"]["active"])

    def test_28_v1_results_are_separate_from_v2(self):
        self.assertTrue((ROOT / "results/multisource_synthetic_water/run_manifest.json").exists())
        self.assertNotEqual((ROOT / "results/multisource_synthetic_water").resolve(),
                            (ROOT / "results/multisource_fusion_v2").resolve())

    def test_29_only_multisource_scene_enables_simulated_water(self):
        text=(ROOT/'src/floodroute/ui/app_v1_1.py').read_text(encoding='utf-8')
        self.assertIn("'异步多源机制实验': 'MULTISOURCE_V2'",text)
        self.assertIn("kind == 'MULTISOURCE_V2'",text)
        self.assertIn("kind in {'REAL', 'MULTISOURCE_V2'}",text)
        self.assertIn('show_risk or show_sensors or',text)

    def test_30_real_ui_keeps_water_disabled_label(self):
        text=(ROOT/'src/floodroute/ui/app_v1_1.py').read_text(encoding='utf-8')
        self.assertIn('真实水位数据：未启用',text)
        self.assertIn("if kind == 'REAL'",text)

    def test_31_persistent_map_instance_and_sensor_update(self):
        text=(ROOT/'src/floodroute/ui/components/leaflet_picker/frontend/picker.js').read_text(encoding='utf-8')
        self.assertEqual(text.count('L.map('),1); self.assertIn('setSensorLayer',text)

    def test_32_sensor_popup_marks_simulation_and_missing(self):
        text=(ROOT/'src/floodroute/ui/components/leaflet_picker/frontend/picker.js').read_text(encoding='utf-8')
        self.assertIn('不代表真实道路积水深度',text); self.assertIn('暂无可靠数据',text)

    def test_33_ground_truth_not_exposed_by_ui_adapter(self):
        text=(ROOT/'src/floodroute/ui/multisource_v2.py').read_text(encoding='utf-8')
        self.assertNotIn("'latent_ponding_truth'",text.split('def multisource_snapshot',1)[1])


if __name__ == "__main__": unittest.main()
