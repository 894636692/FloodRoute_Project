import json, unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]


class RealPipelineTests(unittest.TestCase):
    def test_three_routes_and_provenance(self):
        base=ROOT/'results/real_pipeline'
        metrics=json.loads((base/'real_pipeline_metrics.json').read_text())
        for mode in ['shortest','risk','trusted']:
            route=json.loads((base/f'real_{mode}.geojson').read_text())['features'][0]
            self.assertGreater(metrics['routes'][mode]['distance_m'],0)
            self.assertTrue(route['properties']['edge_ids'])
            coords=np.array(route['geometry']['coordinates'])
            self.assertTrue(((coords[:,0]>113)&(coords[:,0]<115)).all())
        self.assertEqual(metrics['rain_mm_max'],0)
        provenance=json.loads((base/'data_provenance.json').read_text())
        self.assertFalse(provenance['water_source_active'])
