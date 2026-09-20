import sys, unittest
from pathlib import Path
import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, box
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from floodroute.gis.grid_mapping import build_mapping

class MappingTests(unittest.TestCase):
    def test_formal_mapping(self):
        import pandas as pd, json
        w=pd.read_parquet(ROOT/'data/derived/mappings/edge_grid_weights.parquet')
        c=pd.read_parquet(ROOT/'data/derived/mappings/edge_coverage.parquet')
        report=json.loads((ROOT/'data/derived/mappings/coverage_report.json').read_text())
        self.assertEqual(len(c),112218)
        self.assertEqual(set(map(tuple,w[['u','v','key']].values)),set(map(tuple,c[['u','v','key']].values)))
        self.assertTrue(w.weight.between(0,1).all())
        np.testing.assert_allclose(w.groupby(['u','v','key']).weight.sum(),1,atol=1e-10)
        self.assertGreaterEqual(report['road_length_coverage'],.95)

    def test_intersection_weights_and_uncovered_length(self):
        e=gpd.GeoDataFrame({'u':[1,2,3],'v':[2,3,4],'key':[0,0,0],'length_m':[4.,4.,1.]},
            geometry=[LineString([(0,1),(4,1)]),LineString([(2,2),(6,2)]),LineString([(8,1),(9,1)])],crs=32650)
        g=gpd.GeoDataFrame({'grid_id':['a','b']}, geometry=[box(0,0,1,3),box(1,0,4,3)],crs=32650)
        w,c,r=build_mapping(e,g)
        np.testing.assert_allclose(w.groupby(['u','v','key']).weight.sum(),1)
        np.testing.assert_allclose(w[w.u.eq(1)].weight,[.25,.75])
        np.testing.assert_allclose(c.coverage_fraction,[1,.5,0])
        self.assertAlmostEqual(r['road_length_coverage'],6/9)
        self.assertEqual(set(w.u),{1,2})
        with self.assertRaises(ValueError): build_mapping(e.to_crs(4326),g)
