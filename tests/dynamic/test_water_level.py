"""合成数据只存在于测试内存中，不写入真实数据目录。"""

from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from floodroute.dynamic.water_level import RAW_FIELDS, prepare_water_interim, summarize_water


class WaterInterimTests(unittest.TestCase):
    def setUp(self):
        self.stations = pd.DataFrame({"station_id": ["001"], "name": ["测试站"], "station_type": ["waterlogging"]}, dtype="string")

    def prepare(self, rows):
        return prepare_water_interim(pd.DataFrame(rows, columns=RAW_FIELDS, dtype="string"), self.stations)

    def test_conversion_sorting_and_raw_preservation(self):
        raw = pd.DataFrame([
            ["001", "\t2026-09-18 02:00:00", ".1", "02"],
            ["001", "2026-09-18 01:00:00", ".01", "01"],
        ], columns=RAW_FIELDS, dtype="string")
        before = raw.copy(deep=True)
        result = prepare_water_interim(raw, self.stations)
        pd.testing.assert_frame_equal(raw, before)
        pd.testing.assert_frame_equal(result.sort_values("source_record_number")[RAW_FIELDS].reset_index(drop=True), before)
        self.assertEqual(result["station_id"].tolist(), ["001", "001"])
        self.assertEqual(result["water_level_cm"].tolist(), [1.0, 10.0])
        self.assertEqual(result["source_record_id"].tolist(), ["01", "02"])
        self.assertTrue(result["retrieved_at"].isna().all())
        self.assertNotIn("timestamp", result.columns)
        self.assertIsNone(pd.to_datetime(result["source_time_without_timezone"]).dt.tz)
        self.assertTrue(result["quality_flag"].str.contains("timezone_unknown").all())
        report = summarize_water(result)
        self.assertEqual(report["stations_with_unsorted_input"], 1)
        self.assertTrue(report["valid_times_sorted_within_station"])

    def test_same_and_conflicting_duplicates_kept(self):
        result = self.prepare([
            ["001", "2026-09-18 01:00:00", ".01", "a"],
            ["001", "2026-09-18 01:00:00", "0.010", "b"],
            ["001", "2026-09-18 02:00:00", ".01", "c"],
            ["001", "2026-09-18 02:00:00", ".02", "d"],
        ])
        self.assertEqual(len(result), 4)
        self.assertTrue(result.loc[:1, "quality_flag"].str.contains("duplicate_station_timestamp_same_value").all())
        self.assertTrue(result.loc[2:, "quality_flag"].str.contains("duplicate_station_timestamp_conflict").all())
        report = summarize_water(result)
        self.assertEqual(report["duplicate_station_time_groups"], 2)
        self.assertEqual(report["duplicate_station_time_affected_rows"], 4)
        self.assertEqual(report["rows_removed"], 0)

    def test_invalid_missing_and_negative_values_not_dropped(self):
        result = self.prepare([
            ["001", "2026-09-18 01:00:00", "bad", "a"],
            ["001", "2026-09-18 01:00:00", "0.01", "b"],
            ["001", "2026-09-18 02:00:00", "-0.02", "c"],
            ["001", "2026-09-18 03:00:00", "inf", "d"],
            ["001", "", "", "e"],
            ["001", "2026-02-30 01:00:00", "0", "f"],
            ["001", "2026-09-18T01:00:00+08:00", "0", "g"],
        ]).set_index("source_record_id")
        self.assertEqual(len(result), 7)
        self.assertIn("duplicate_station_timestamp_review", result.loc["a", "quality_flag"])
        self.assertIn("water_level_invalid", result.loc["d", "quality_flag"])
        self.assertTrue(pd.isna(result.loc["d", "water_level_cm"]))
        self.assertEqual(result.loc["c", "water_level_cm"], -2.0)
        self.assertIn("negative_water_level_review", result.loc["c", "quality_flag"])
        self.assertIn("water_level_missing", result.loc["e", "quality_flag"])
        for key in ["f", "g"]:
            self.assertIn("source_time_parse_error", result.loc[key, "quality_flag"])
            self.assertTrue(pd.isna(result.loc[key, "source_time_without_timezone"]))

    def test_unmatched_and_missing_station_ids_flagged(self):
        result = self.prepare([
            ["999", "2026-09-18 01:00:00", "0", "a"],
            ["", "2026-09-18 01:00:00", "0", "a"],
        ])
        flags = result.set_index("station_id")["quality_flag"]
        self.assertIn("station_not_found", flags["999"])
        self.assertIn("station_id_missing", flags[""])
        self.assertTrue(result["quality_flag"].str.contains("duplicate_source_record_id").all())

    def test_bad_schema_and_ambiguous_station_lookup_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare([])
        with self.assertRaises(ValueError):
            prepare_water_interim(pd.DataFrame({"wrong": ["x"]}), self.stations)
        raw = pd.DataFrame([["001", "2026-09-18 01:00:00", "0", "a"]], columns=RAW_FIELDS, dtype="string")
        with self.assertRaises(ValueError):
            prepare_water_interim(raw, pd.concat([self.stations, self.stations]))
        raw["测站编码"] = 1
        with self.assertRaises(ValueError):
            prepare_water_interim(raw, self.stations)
