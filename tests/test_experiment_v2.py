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


class ExperimentV2Tests(unittest.TestCase):
    def test_partition_disjoint_and_duplicate_guards(self):
        validate_split({'calibration': [1], 'validation': [2], 'test': [3]})
        for split in [{'calibration':[1], 'validation':[1], 'test':[3]},
                      {'calibration':[1,1], 'validation':[2], 'test':[3]},
                      {'calibration':[], 'validation':[2], 'test':[3]}]:
            with self.assertRaises(ValueError): validate_split(split)

    def test_profiles_preserve_base_and_water_disabled(self):
        base = load_config(); original = copy.deepcopy(base)
        design = json.loads((ROOT/'config/experiment_v2.json').read_text())
        for params in design['candidates'].values():
            cfg = profile_config(base, params)
            self.assertFalse(cfg['sources']['water']['active'])
            self.assertEqual(cfg['static'], base['static'])
            self.assertEqual(cfg['sources']['rain']['scale'], base['sources']['rain']['scale'])
        self.assertEqual(base, original)

    def test_ablation_changes_only_intended_parameters(self):
        params = json.loads((ROOT/'config/experiment_v2.json').read_text())['candidates']['baseline']
        cfg = profile_config(load_config(), params, 'no_freshness')
        self.assertEqual(cfg['trusted']['staleness_weight'], 0)
        self.assertEqual(cfg['trusted']['uncertainty_weight'], params['uncertainty_weight'])
        cfg = profile_config(load_config(), params, 'universal')
        self.assertTrue(all(s['tau_min'] == 60 for s in cfg['sources'].values()))


    def test_saved_selection_and_test_seed_separation(self):
        folder = ROOT/'results/experiment_v2'
        split = json.loads((folder/'scenario_split.json').read_text())
        validate_split(split)
        selection = json.loads((folder/'parameter_selection.json').read_text())
        manifest = json.loads((folder/'run_manifest.json').read_text())
        digest = hashlib.sha256((folder/'parameter_selection.json').read_bytes()).hexdigest()
        self.assertFalse(selection['test_used_for_selection'])
        self.assertEqual(digest, manifest['selection_sha256_before_test'])
        self.assertEqual(digest, manifest['selection_sha256_after_test'])
        test = pd.read_csv(folder/'test_routes.csv')
        self.assertEqual(set(test.seed), set(split['test']))
        for path in folder.glob('calibration_*.csv'):
            self.assertEqual(set(pd.read_csv(path).seed), set(split['calibration']))
        for path in folder.glob('validation_*.csv'):
            self.assertEqual(set(pd.read_csv(path).seed), set(split['validation']))



    def test_heldout_complete_factorial_and_finite_metrics(self):
        import numpy as np
        rows = pd.read_csv(ROOT/'results/experiment_v2/test_routes.csv')
        self.assertEqual(len(rows), 3*2*2*5*3*2*3*4)
        self.assertEqual(set(rows['mode']), {'shortest','risk','risk_uncertainty','trusted'})
        self.assertEqual(set(rows.ablation), {'no_freshness','universal','source_specific'})
        self.assertTrue(np.isfinite(rows[['distance_m','truth_exposure','max_truth_risk','p95_truth_risk',
                                         'high_risk_length_ratio','computation_ms']]).all().all())
        self.assertFalse(rows.duplicated(['seed','od','decision_step','delay_min','missing_rate','noise','ablation','mode']).any())
