import sys, unittest, json
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from floodroute.experiments.scenario import generate_truth,observe


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        cfg=json.loads((ROOT/'config/final_v1.json').read_text())
        grids=gpd.GeoDataFrame({'grid_id':['a','b','c']},geometry=[box(0,0,1,1),box(1,1,2,2),box(2,2,3,3)],crs=32650)
        self.truth=generate_truth(grids,cfg)
        pd.testing.assert_frame_equal(self.truth,generate_truth(grids,cfg))

    def test_reproducible_observed_and_no_future(self):
        now=pd.Timestamp('2023-09-07T15:00:00+08:00')
        a=observe(self.truth,now,30,.2,.1,42)
        pd.testing.assert_frame_equal(a,observe(self.truth,now,30,.2,.1,42))
        self.assertTrue(a.timestamp.le(now-pd.Timedelta(minutes=30)).all())
        self.assertNotIn('truth_rain_mm',a)
        self.assertNotIn('random_seed',a)
        self.assertTrue(self.truth.scenario_type.eq('simulated_extreme').all())

    def test_future_truth_cannot_change_current_observed(self):
        now=self.truth.timestamp.iloc[0]
        original=observe(self.truth,now,seed=1)
        changed=self.truth.copy();changed.loc[changed.timestamp.gt(now),'rain_mm']=999999
        pd.testing.assert_frame_equal(original,observe(changed,now,seed=1))
        self.assertTrue(observe(self.truth,now,missing_rate=1).empty)
