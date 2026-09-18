from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import networkx as nx

from floodroute.common.schema import CALCULATION_CRS, ROAD_STATIC_REQUIRED_FIELDS, RouteRequest
from floodroute.experiments.trigger_experiment import run_delay_experiment
from floodroute.risk.models import DynamicObservationMatcher, EdgeRiskEngine, validate_static_edges
from floodroute.routing.router import RoadNetworkRouter
from floodroute.routing.service import plan_from_files


STATIC_PATH = ROOT / "data" / "derived" / "static" / "road_static_features.gpkg"
RAINFALL_PATH = ROOT / "data" / "derived" / "dynamic" / "rainfall.csv"
WATER_PATH = ROOT / "data" / "derived" / "dynamic" / "water_level.csv"
REQUEST_PATH = ROOT / "examples" / "request_trusted.json"
TEST_TMP = ROOT / "results" / "test_tmp"


def make_test_dir() -> Path:
    path = TEST_TMP / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


@unittest.skipUnless(STATIC_PATH.exists(), "prepared B static fixture is not available")
class TestBRoutingInterface(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.edges = gpd.read_file(STATIC_PATH)
        cls.request_data = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))

    def test_static_fixture_matches_a_to_b_schema(self) -> None:
        self.assertEqual(str(self.edges.crs), CALCULATION_CRS)
        self.assertTrue(ROAD_STATIC_REQUIRED_FIELDS.issubset(set(self.edges.columns)))
        validate_static_edges(self.edges)

    def test_router_preserves_osm_multidigraph_edge_ids(self) -> None:
        router = RoadNetworkRouter(self.edges)
        self.assertIsInstance(router.graph, nx.MultiDiGraph)
        sample = self.edges.iloc[0]
        edge_id = (int(sample.u), int(sample.v), int(sample.key))
        self.assertIn(edge_id, router.graph.edges(keys=True))

    def test_shortest_risk_and_trusted_modes_return_b_to_c_response(self) -> None:
        for mode in ("shortest", "risk", "trusted"):
            request_data = dict(self.request_data, mode=mode)
            tmpdir = make_test_dir()
            request_path = tmpdir / f"request_{mode}.json"
            output_path = tmpdir / f"response_{mode}.json"
            request_path.write_text(json.dumps(request_data), encoding="utf-8")
            response = plan_from_files(
                request_path,
                STATIC_PATH,
                output_path,
                rainfall_csv=str(RAINFALL_PATH),
                water_level_csv=str(WATER_PATH),
            )
            self.assertGreater(response["distance_m"], 0)
            self.assertGreater(response["travel_time_s"], 0)
            self.assertIn("geometry_geojson", response)
            self.assertTrue(response["edge_ids"])
            self.assertTrue(all(len(edge_id) == 3 for edge_id in response["edge_ids"]))

    def test_ground_truth_fields_are_not_required_for_planning(self) -> None:
        matcher = DynamicObservationMatcher()
        dynamic = matcher.attach_dynamic(
            self.edges,
            timestamp=self.request_data["timestamp"],
            rainfall_csv=str(RAINFALL_PATH),
            water_level_csv=str(WATER_PATH),
        )
        self.assertNotIn("ground_truth", dynamic.columns)
        states = EdgeRiskEngine().build_edge_states(self.edges, self.request_data["timestamp"], dynamic)
        request = RouteRequest.from_dict(self.request_data)
        route = RoadNetworkRouter(self.edges).plan(request, states)
        self.assertGreater(route.distance_m, 0)

    def test_trigger_experiment_outputs_metrics(self) -> None:
        request = RouteRequest.from_dict(self.request_data)
        output = make_test_dir() / "trigger.csv"
        rows = run_delay_experiment(
            STATIC_PATH,
            request,
            {0: str(RAINFALL_PATH), 30: str(RAINFALL_PATH)},
            {0: str(WATER_PATH), 30: str(WATER_PATH)},
            output,
        )
        self.assertEqual(len(rows), 2)
        self.assertIn("replan_count", rows[-1])
        self.assertIn("route_change_count", rows[-1])


if __name__ == "__main__":
    unittest.main()
