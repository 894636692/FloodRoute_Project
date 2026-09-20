import sys, unittest, json, copy
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from floodroute.risk.trusted import RiskEngine
from floodroute.risk.dynamic import quality_penalty, map_rainfall
from floodroute.risk.freshness import freshness

class RiskTests(unittest.TestCase):
    def setUp(self):
        self.cfg=json.loads((ROOT/'config/final_v1.json').read_text())
        self.edges=pd.DataFrame([dict(u=1,v=2,key=0,low_elev_norm=.5,flatness_risk=.5,builtup_frac=.5,
            water_frac=0.,vegetation_frac=.5,dem_valid_frac=1.,slope_valid_frac=1.,worldcover_valid_frac=1.,quality_flag='ok')])
        self.index=pd.MultiIndex.from_frame(self.edges[['u','v','key']])
        self.rain=pd.DataFrame(dict(value=[20.],age_min=[30.],coverage=[1.],quality=[0.]),index=self.index)

    def test_inactive_water_does_not_penalize(self):
        e=RiskEngine(self.edges,self.cfg)
        pd.testing.assert_frame_equal(e.compute({'rain':self.rain}),e.compute({'rain':self.rain,'water':self.rain*100}))
        self.assertNotIn('water_freshness',e.compute({'rain':self.rain}))

    def test_nan_explicit_prior_and_missing_uncertainty(self):
        complete=RiskEngine(self.edges,self.cfg).compute({'rain':self.rain})
        self.edges.loc[0,'low_elev_norm']=np.nan
        missing=RiskEngine(self.edges,self.cfg).compute({'rain':self.rain})
        self.assertGreater(missing.uncertainty.iloc[0],complete.uncertainty.iloc[0])
        self.assertAlmostEqual(missing.static_risk.iloc[0],complete.static_risk.iloc[0])
        self.assertGreater(missing.static_missing_fraction.iloc[0],0)

    def test_quality_tokens_separate_taus_and_no_future(self):
        self.assertEqual(quality_penalty('ok;bad;other'),1)
        self.assertLess(freshness([30],20)[0],freshness([30],90)[0])
        with self.assertRaises(ValueError):freshness([10],0)
        w=pd.DataFrame(dict(u=[1],v=[2],key=[0],grid_id=['a'],weight=[1.]))
        c=pd.DataFrame(dict(u=[1],v=[2],key=[0],coverage_fraction=[1.]))
        obs=pd.DataFrame(dict(grid_id=['a','a'],timestamp=['2023-01-01T00:00:00+08:00','2023-01-01T02:00:00+08:00'],rain_mm=[10,100],quality_flag=['ok','ok']))
        out=map_rainfall(obs,w,c,'2023-01-01T01:00:00+08:00')
        self.assertEqual(out.value.iloc[0],10)
        self.assertEqual(out.age_min.iloc[0],60)

    def test_all_inactive_and_active_missing_are_distinct(self):
        missing=RiskEngine(self.edges,self.cfg).compute({})
        self.cfg['sources']['rain']['active']=False
        inactive=RiskEngine(self.edges,self.cfg).compute({})
        self.assertEqual(inactive.freshness.iloc[0],1)
        self.assertLess(missing.confidence.iloc[0],inactive.confidence.iloc[0])
