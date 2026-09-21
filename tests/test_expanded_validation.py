import hashlib
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from floodroute.experiments.expanded import FAMILIES, generate_family_truth, observation_digest


ROOT = Path(__file__).resolve().parents[1]


class ExpandedValidationTests(unittest.TestCase):
    def setUp(self):
        self.grids = gpd.GeoDataFrame(
            {"grid_id": ["1", "2", "3", "4"]},
            geometry=[box(0, 0, 1, 1), box(9, 0, 10, 1), box(0, 9, 1, 10), box(9, 9, 10, 10)],
            crs="EPSG:32650",
        )

    def test_families_are_deterministic_and_distinct(self):
        frames = [generate_family_truth(self.grids, [0, 0, 10, 10], family, 7101, "2023-09-07T12:00:00+08:00") for family in FAMILIES]
        for family, frame in zip(FAMILIES, frames):
            repeat = generate_family_truth(self.grids, [0, 0, 10, 10], family, 7101, "2023-09-07T12:00:00+08:00")
            pd.testing.assert_frame_equal(frame, repeat)
            self.assertEqual(frame.timestamp.nunique(), 12)
            self.assertEqual(frame.grid_id.nunique(), 4)
        digests = {observation_digest(frame) for frame in frames}
        self.assertEqual(len(digests), 3)

    def test_frozen_config_hash_and_water_setting(self):
        raw = (ROOT / "config/selected_v1_1.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "3f8ea08239d12d19b801afec28b5156625dd08daef4f54ff72573756bd7e6dd5")
        import json
        config = json.loads(raw)
        self.assertFalse(config["sources"]["water"]["active"])


if __name__ == "__main__":
    unittest.main()
