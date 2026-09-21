import ast
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HistoricalValidationBoundaryTests(unittest.TestCase):
    def test_planner_and_risk_do_not_import_historical_labels(self):
        protected = [ROOT / "src/floodroute/runtime.py", ROOT / "src/floodroute/risk", ROOT / "src/floodroute/routing"]
        for base in protected:
            files = [base] if base.is_file() else list(base.rglob("*.py"))
            for path in files:
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imports.append(node.module or "")
                joined = " ".join(imports).lower()
                self.assertNotIn("historical", joined, path)
                self.assertNotIn("impact_report", joined, path)

    def test_label_matching_preserves_exact_edge_and_thresholds(self):
        module = load_script("build_historical_event_labels.py")
        reports = pd.DataFrame([{
            "report_id": "R1", "reported_time_start": "2023-09-08T10:00:00+08:00",
            "reported_time_end": "2023-09-08T11:00:00+08:00", "lon": 114.0, "lat": 22.55,
            "geocode_method": "OSM_name_match", "match_confidence": "high",
        }])
        point = gpd.GeoSeries.from_xy([114.0], [22.55], crs="EPSG:4326").to_crs("EPSG:32650").iloc[0]
        roads = gpd.GeoDataFrame([{
            "u": 1, "v": 2, "key": 3, "osm_way_id": 4, "highway": "trunk",
            "length_m": 100.0, "static_risk": 0.4,
            "geometry": LineString([(point.x - 10, point.y), (point.x + 10, point.y)]),
        }], crs="EPSG:32650")
        labels, summary = module.build_labels(reports, roads)
        self.assertEqual((int(labels.iloc[0].u), int(labels.iloc[0].v), int(labels.iloc[0].key)), (1, 2, 3))
        self.assertTrue(bool(labels.iloc[0].within_50m))
        self.assertTrue(bool(labels.iloc[0].eligible_main))
        self.assertEqual(summary["main_eligible_rows"], 1)

    def test_power_normalization_uses_end_of_hour_and_timezone(self):
        module = load_script("download_historical_forcing.py")
        payload = {
            "header": {"time_standard": "UTC", "title": "x", "api": {}, "sources": ["MERRA2"]},
            "parameters": {"PRECTOTCORR": {"units": "mm/hour"}},
            "properties": {"parameter": {"PRECTOTCORR": {"2023090710": 2.5}}},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grids.csv"
            pd.DataFrame({"grid_id": ["1"], "lon": [114.0], "lat": [22.5]}).to_csv(path, index=False)
            frame, metadata = module.normalize_power_response(json.dumps(payload).encode(), path)
        self.assertEqual(frame.iloc[0].window_start.isoformat(), "2023-09-07T18:00:00+08:00")
        self.assertEqual(frame.iloc[0].timestamp.isoformat(), "2023-09-07T19:00:00+08:00")
        self.assertEqual(float(frame.iloc[0].rain_mm), 2.5)
        self.assertFalse(metadata["street_scale_truth"])


if __name__ == "__main__":
    unittest.main()
