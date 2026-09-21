"""Source-backed map query and compact layer regressions."""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from floodroute.ui.map_data import (build_query_result, latest_rainfall,
    rainfall_layer_values, road_risk_layer_values, safe_road_name)
from floodroute.ui.observations import get_observations, scenario_times
from floodroute.ui.resources import load_runtime, grid_registry, risk_display_edge_ids


class RainfallQueryUnitTests(unittest.TestCase):
    def setUp(self):
        self.at = pd.Timestamp('2026-09-18T01:00:00+08:00')

    def test_latest_preceding_hour_and_compact_levels(self):
        data = pd.DataFrame({
            'grid_id':['A','A','B'],
            'timestamp':pd.to_datetime(['2026-09-17T16:30:00Z','2026-09-17T17:00:00Z','2026-09-17T17:00:00Z'], utc=True),
            'retrieved_at':pd.to_datetime(['2026-09-17T16:31:00Z','2026-09-17T17:01:00Z','2026-09-17T17:00:00Z'], utc=True),
            'rain_mm':[2.,99.,26.]})
        latest = latest_rainfall(data, self.at)
        self.assertEqual(latest.set_index('grid_id').loc['A','rain_mm'],2.)
        self.assertEqual(rainfall_layer_values(data,self.at),[['A',2.0,1],['B',26.0,3]])

    def test_missing_rain_is_unknown_never_zero(self):
        data=pd.DataFrame({'grid_id':['A'],'timestamp':[self.at],'rain_mm':[np.nan]})
        self.assertEqual(rainfall_layer_values(data,self.at),[['A',None,-1]])

    def test_no_unsupported_accumulation_fields_exist(self):
        source=(ROOT/'src/floodroute/ui/map_data.py').read_text(encoding='utf-8')
        for label in ('rain_3h','rain_6h','rain_24h','近3小时','近6小时','近24小时'):
            self.assertNotIn(label,source)

    def test_unreliable_road_name_is_unknown(self):
        self.assertIsNone(safe_road_name('坏�路名'))
        self.assertEqual(safe_road_name('深南大道'),'深南大道')


class FormalMapQueryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime=load_runtime()
        cls.at=scenario_times('REAL')[-1]
        cls.observed=get_observations('REAL',cls.at)
        cls.state, sources=cls.runtime.observed_state_with_sources(cls.observed,cls.at)
        cls.mapped=sources['rain']

    def test_real_query_uses_formal_grid_road_and_current_state(self):
        result=build_query_result(self.runtime,grid_registry(),self.observed,self.state,
                                  self.mapped,self.at,114.055,22.545,'REAL')
        self.assertTrue(result['grid_id'])
        self.assertEqual(result['rain_interval_min'],60)
        self.assertIsNotNone(result['rain_mm'])
        self.assertEqual(result['rain_source'],'深圳市气象局（台）')
        self.assertAlmostEqual(result['road']['risk'],
            float(self.state.loc[tuple(map(int,result['road']['edge_id'].split(':'))),'risk']))
        self.assertEqual(result['water_status'],'真实水位数据：未启用')
        self.assertNotIn('water_level_cm',result)

    def test_compact_payloads_contain_values_not_geometry(self):
        rain=rainfall_layer_values(self.observed,self.at)
        road=road_risk_layer_values(self.state,risk_display_edge_ids())
        self.assertEqual(len(rain),4232)
        self.assertGreater(len(road),20_000)
        self.assertTrue(all(len(item)==3 for item in rain[:20]+road[:20]))
        self.assertFalse(any(isinstance(value,dict) for item in rain[:20]+road[:20] for value in item))


if __name__ == '__main__':
    unittest.main()
