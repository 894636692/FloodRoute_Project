import unittest,json
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]

class ExperimentOutputTests(unittest.TestCase):
    def test_full_factorial_and_time_replay(self):
        data=pd.read_csv(ROOT/'results/scenario_experiments/independent.csv')
        self.assertEqual(len(data),360)
        self.assertEqual(data.groupby(['delay_min','missing_rate','noise']).size().tolist(),[8]*45)
        self.assertFalse(data[['distance_m','truth_exposure','p95_truth_risk','computation_ms']].isna().any().any())
        replay=pd.read_csv(ROOT/'results/trigger_replay/replay.csv')
        self.assertEqual(len(replay),51)
        for _,group in replay.groupby('policy'):
            self.assertTrue(pd.to_datetime(group.timestamp).is_monotonic_increasing)
        summary=json.loads((ROOT/'results/trigger_replay/summary.json').read_text())
        modes={r['policy']:r for r in summary['summary']}
        self.assertEqual(modes['always']['replan_count'],16)
        self.assertLess(modes['triggered']['replan_count'],modes['always']['replan_count'])
