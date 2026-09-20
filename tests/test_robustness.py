import sys,unittest
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from v1_helpers import mini_runtime
from floodroute.experiments.robustness import run_independent

class RobustnessTests(unittest.TestCase):
    def test_reproducible_and_order_independent_routes(self):
        runtime,truth,request=mini_runtime()
        combinations=[(0,0,0),(30,.2,.1)]
        a=run_independent(runtime,truth,request,combinations)
        b=run_independent(runtime,truth,request,list(reversed(combinations)))
        cols=[c for c in a if not c.endswith('_ms')]
        pd.testing.assert_frame_equal(a[cols],b[cols])
        self.assertEqual(len(a),16)
        self.assertEqual(set(a['mode']),{'shortest','risk','risk_uncertainty','trusted'})
        self.assertTrue(a.truth_exposure.between(0,1).all())
