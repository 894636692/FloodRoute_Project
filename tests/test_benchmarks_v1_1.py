import sys
import copy
import hashlib
import json
import unittest
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from floodroute.experiments.v2 import validate_split, profile_config
from floodroute.runtime import load_config
from floodroute.experiments.benchmarks import benchmark_truth
from floodroute.experiments.scenario import observe
from v1_helpers import mini_runtime
import geopandas as gpd
from shapely.geometry import box


class BenchmarkV11Tests(unittest.TestCase):
    def test_benchmark_reproducible_and_future_invariant(self):
        grids = gpd.GeoDataFrame({'grid_id': ['1','2']}, geometry=[box(0,0,100,100),box(100,0,200,100)],crs=32650)
        truth = benchmark_truth(grids, load_config(), [50,50], 'T1', 4101)
        pd.testing.assert_frame_equal(truth, benchmark_truth(grids, load_config(), [50,50], 'T1',4101))
        changed = truth.copy(); at = truth.timestamp.iloc[4]
        changed.loc[changed.timestamp > at, 'rain_mm'] = 99999
        pd.testing.assert_frame_equal(observe(truth, at), observe(changed, at))
        self.assertGreater(truth.groupby('timestamp').rain_mm.mean().iloc[-1], truth.rain_mm.iloc[0])

    def test_T1_switches_with_improvement_on_all_test_seeds(self):
        folder = ROOT/'results/experiment_v2'
        split = json.loads((folder/'scenario_split.json').read_text())
        for seed in split['test']:
            rows = pd.read_csv(folder/f'T1_{seed}_replay.csv')
            changed = rows[rows.policy.eq('triggered') & rows.route_changed]
            self.assertGreaterEqual(len(changed), 1)
            self.assertTrue((changed.candidate_improvement > 0).all())
            self.assertTrue((changed.truth_exposure < changed.initial_route_truth_exposure).all())

    def test_T2_reduces_planning_without_exposure_penalty(self):
        folder = ROOT/'results/experiment_v2'
        split = json.loads((folder/'scenario_split.json').read_text())
        for seed in split['test']:
            rows = pd.read_csv(folder/f'T2_{seed}_replay.csv')
            a = rows[rows.policy.eq('always')]; t = rows[rows.policy.eq('triggered')]
            self.assertLess(t.planner_calls.max(), a.planner_calls.max())
            self.assertLessEqual(t.truth_exposure.mean(), a.truth_exposure.mean()+.01)
