import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ab_runtime
import numpy as np
from osgeo import ogr, osr
from floodroute.gis.static_features import (
    build_osm_graph, direction, extract_features, sample_positions, spatial_ref,
)


class StaticInterfaceTests(unittest.TestCase):
    def test_direction(self):
        self.assertEqual(direction({"oneway": "-1"}), "reverse")
        self.assertEqual(direction({"junction": "roundabout"}), "forward")
        self.assertEqual(direction({"highway": "motorway"}), "forward")
        self.assertEqual(direction({"highway": "motorway", "oneway": "no"}), "both")
        self.assertEqual(direction({"oneway": "reversible"}), "unsupported")

    def test_real_node_identity_and_parallel_keys(self):
        coords = {1: (114, 22.55), 2: (114.001, 22.55), 3: (114.002, 22.55),
                  4: (114.001, 22.551), 5: (114.001, 22.549),
                  6: (114, 22.55), 7: (114.001, 22.55)}
        elements = [{"type": "node", "id": n, "lon": xy[0], "lat": xy[1]} for n, xy in coords.items()]
        for way_id, nodes, tags in [(10, [1, 2, 3], {"oneway": "yes"}),
                                   (11, [2, 4], {}), (12, [1, 2], {"oneway": "yes"}),
                                   (13, [2, 5], {"oneway": "-1"}), (14, [6, 7], {})]:
            elements.append(dict(type="way", id=way_id, nodes=nodes, tags=dict(highway="residential", **tags)))
        area = ogr.CreateGeometryFromWkt("POLYGON ((113.99 22.54,114.01 22.54,114.01 22.56,113.99 22.56,113.99 22.54))")
        area.Transform(osr.CoordinateTransformation(spatial_ref("EPSG:4326"), spatial_ref("EPSG:32650")))
        graph, records, _ = build_osm_graph(dict(elements=elements), area)
        self.assertEqual(set(graph[1][2]), {0, 1})
        self.assertFalse(graph.has_edge(2, 1))
        self.assertTrue(graph.has_edge(5, 2))
        self.assertFalse(graph.has_edge(2, 5))
        self.assertTrue(graph.has_edge(2, 3))
        self.assertFalse(graph.has_edge(6, 2))
        self.assertEqual(len(records), 8)

    def test_whole_line_and_flatness(self):
        geometry = ogr.CreateGeometryFromWkt("LINESTRING (1 15,89 15)")
        config = {"sample_spacing_m": 10, "min_edge_coverage": 0.9,
                  "flatness_zero_at_deg": 15, "vegetation_classes": [10, 20, 30, 40, 90, 95, 100]}
        arrays = {"dem": np.array([[10., 100., 10.]]), "slope": np.array([[0., 15., 0.]]),
                  "worldcover": np.array([[50., 10., 80.]])}
        result = extract_features(geometry, arrays, (0, 30, 0, 30, 0, -30), config, (0, 100))
        self.assertAlmostEqual(result["elev_mean_m"], 40)
        self.assertAlmostEqual(result["flatness_risk"], 2 / 3)
        for field in ("builtup_frac", "vegetation_frac", "water_frac"):
            self.assertAlmostEqual(result[field], 1 / 3)

    def test_nodata_is_not_zero(self):
        geometry = ogr.CreateGeometryFromWkt("LINESTRING (1 15,89 15)")
        config = {"sample_spacing_m": 10, "min_edge_coverage": 0.9,
                  "flatness_zero_at_deg": 15, "vegetation_classes": [10]}
        arrays = {"dem": np.array([[10., np.nan, 10.]]), "slope": np.array([[0., 0., 0.]]),
                  "worldcover": np.array([[50., 0., 80.]])}
        result = extract_features(geometry, arrays, (0, 30, 0, 30, 0, -30), config, (0, 100))
        self.assertIsNone(result["elev_mean_m"])
        self.assertIsNone(result["builtup_frac"])
        self.assertEqual(result["flatness_risk"], 1)
        self.assertAlmostEqual(result["dem_valid_frac"], 2 / 3)

    def test_curved_geometry_sampling(self):
        geometry = ogr.CreateGeometryFromWkt("LINESTRING (0 0,100 0,100 100)")
        positions = sample_positions(geometry, 10)
        self.assertEqual(len(positions), 20)
        self.assertTrue(np.all(positions[:10, 1] == 0))
        self.assertTrue(np.all(positions[10:, 0] == 100))


if __name__ == "__main__":
    ogr.UseExceptions()
    unittest.main(verbosity=2)
