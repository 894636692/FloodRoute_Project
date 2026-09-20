import sys, unittest, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from floodroute.dynamic.grid_source import read_rainfall


class GridSourceTests(unittest.TestCase):
    def test_actual_rainfall_contract(self):
        data = read_rainfall(ROOT / 'data/derived/dynamic/shenzhen_grid/rainfall.csv')
        self.assertEqual(len(data), 100000)
        self.assertEqual(data.grid_id.nunique(), 4232)
        self.assertTrue(data.rain_mm.eq(0).all())
        self.assertTrue(data.coordinate_role.eq('grid_center_not_station').all())
        self.assertTrue(data.retrieved_at.isna().all())

    def test_real_water_inactive(self):
        cfg = json.loads((ROOT / 'config/final_v1.json').read_text())
        self.assertFalse(cfg['sources']['water']['active'])
        self.assertFalse(cfg['sources']['forecast']['active'])
