import sys
import unittest
from pathlib import Path
import networkx as nx
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from floodroute.gis.io import read_static
from floodroute.routing.router import RoadNetworkRouter


class FormalStaticTests(unittest.TestCase):
    def test_actual_a_interface_and_multigraph(self):
        edges = read_static(ROOT / 'data/derived/static/road_static_features.gpkg')
        self.assertGreater(len(edges), 100000)
        self.assertTrue(edges.source_version.str.startswith('gis-v1.0.0-').all())
        graph = RoadNetworkRouter(edges).graph
        self.assertIsInstance(graph, nx.MultiDiGraph)
        self.assertEqual(set(graph.edges(keys=True)), set(map(tuple, edges[['u','v','key']].values)))
        self.assertTrue(edges.loc[edges.low_elev_norm.isna(), 'quality_flag'].str.contains('dem').all())
