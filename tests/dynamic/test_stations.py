"""只使用人工构造的测试输入，不写入真实数据目录。"""

from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from floodroute.dynamic.stations import RAW_FIELDS, prepare_station_interim, summarize_stations


class StationInterimTests(unittest.TestCase):
    def test_leading_zero_and_original_values_preserved(self):
        raw = pd.DataFrame([["001", "测试站", "内涝水情站"]], columns=RAW_FIELDS, dtype="string")
        before = raw.copy(deep=True)
        result = prepare_station_interim(raw)
        self.assertEqual(result.loc[0, "station_id"], "001")
        self.assertEqual(result.loc[0, "station_type"], "waterlogging")
        pd.testing.assert_frame_equal(raw, before)
        pd.testing.assert_frame_equal(result[RAW_FIELDS], before)
        self.assertTrue(result[["lon", "lat"]].isna().all().all())
        self.assertEqual(result.loc[0, "coordinate_crs"], "coordinate_crs_unknown")
        self.assertIsNone(summarize_stations(result)["outside_shenzhen_count"])

    def test_anomalies_are_flagged_and_not_dropped(self):
        raw = pd.DataFrame([
            ["001", "甲", "内涝水情站"], ["001", "乙", "河道水位站"],
            ["", "", "新类型"], [pd.NA, pd.NA, pd.NA],
            ["002", "丙", "水库水位站"],
        ], columns=RAW_FIELDS, dtype="string")
        result = prepare_station_interim(raw)
        self.assertEqual(len(result), 5)
        self.assertTrue(result.loc[:1, "quality_flag"].str.contains("duplicate_station_id").all())
        self.assertIn("station_id_missing", result.loc[2, "quality_flag"])
        self.assertIn("name_missing", result.loc[3, "quality_flag"])
        self.assertIn("station_type_unknown", result.loc[2, "quality_flag"])
        self.assertEqual(result.loc[4, "station_type"], "reservoir_water_level")
        report = summarize_stations(result)
        self.assertEqual(report["duplicate_id_extra_rows"], 1)
        self.assertEqual(report["missing_station_id"], 2)
        self.assertEqual(report["rows_removed"], 0)

    def test_numeric_ids_and_changed_schema_are_rejected(self):
        with self.assertRaises(ValueError):
            prepare_station_interim(pd.DataFrame([[1, "甲", "内涝水情站"]], columns=RAW_FIELDS))
        with self.assertRaises(ValueError):
            prepare_station_interim(pd.DataFrame({"STCD": ["001"]}))
