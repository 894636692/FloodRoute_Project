"""内存合成边界用例，不生成假降雨文件。"""

from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from floodroute.dynamic.rainfall import (
    parse_precipitation_group, prepare_noaa_rainfall_interim, summarize_noaa_rainfall,
)


class RainfallTests(unittest.TestCase):
    def raw(self, **changes):
        row = dict(STATION="00123456789", DATE="2025-01-01T20:00:00", NAME="TEST",
                   LATITUDE="22.6", LONGITUDE="113.8", AA1="06,0015,9,1", AA2="")
        row.update(changes)
        return pd.DataFrame([row], dtype="string")

    def prepare(self, raw):
        return prepare_noaa_rainfall_interim(raw, "2026-09-18T10:00:00+08:00")

    def test_units_period_and_missing_sentinels(self):
        parsed = parse_precipitation_group("06,0015,9,1")
        self.assertEqual(parsed["rain_mm"], 1.5)
        self.assertEqual(parsed["interval_min"], 360)
        missing = parse_precipitation_group("99,9999,9,9")
        self.assertIsNone(missing["rain_mm"])
        self.assertIsNone(missing["interval_min"])
        self.assertIn("rain_missing", missing["flags"])
        self.assertIn("interval_unknown", missing["flags"])
        self.assertIn("zero_interval_review", parse_precipitation_group("00,0000,9,1")["flags"])

    def test_special_conditions_are_not_silently_validated(self):
        for condition, expected in [("2", "trace_precipitation"), ("3", "accumulation_begin_review"), ("E", "estimated_precipitation")]:
            parsed = parse_precipitation_group(f"24,0010,{condition},2")
            self.assertEqual(parsed["rain_mm"], 1.0)
            self.assertIn(expected, parsed["flags"])
            self.assertIn("source_qc_suspect", parsed["flags"])
        self.assertIn("precipitation_group_parse_error", parse_precipitation_group("06,-001,9,1")["flags"])

    def test_timezone_and_original_fields_preserved(self):
        raw = self.raw()
        before = raw.copy(deep=True)
        result = self.prepare(raw)
        pd.testing.assert_frame_equal(raw, before)
        self.assertEqual(result.loc[0, "timestamp"], "2025-01-02T04:00:00+08:00")
        self.assertEqual(result.loc[0, "station_id"], "NOAA_ISD_00123456789")
        for column in raw:
            self.assertEqual(result.loc[0, column], raw.loc[0, column])
        self.assertNotIn("lon", result)
        self.assertIn("coordinate_crs_unknown", result.loc[0, "quality_flag"])

    def test_duplicate_groups_and_conflicts_kept(self):
        result = self.prepare(self.raw(AA2="06,0020,9,1"))
        self.assertEqual(len(result), 2)
        self.assertEqual(result["rain_mm"].tolist(), [1.5, 2.0])
        self.assertTrue(result["quality_flag"].str.contains("duplicate_station_time_interval").all())
        self.assertTrue(result["quality_flag"].str.contains("conflicting_rain_values").all())
        distinct = self.prepare(self.raw(AA2="12,0020,9,1"))
        self.assertFalse(distinct["quality_flag"].str.contains("duplicate_station_time_interval").any())

    def test_missing_groups_preserve_weather_record(self):
        result = self.prepare(self.raw(AA1="", AA2=""))
        self.assertEqual(len(result), 1)
        self.assertTrue(result["rain_mm"].isna().all())
        report = summarize_noaa_rainfall(result)
        self.assertEqual(report["raw_weather_record_count"], 1)
        self.assertEqual(report["reported_precipitation_group_count"], 0)
        self.assertEqual(report["rain_missing_rate_in_interim"], 1.0)
        self.assertIsNone(report["reported_rain_min_mm"])

    def test_invalid_times_coordinates_and_future_retained(self):
        result = self.prepare(self.raw(DATE="2025-02-30T00:00:00", LATITUDE="999", LONGITUDE="nan"))
        self.assertTrue(result["timestamp"].isna().all())
        for flag in ["source_time_parse_error", "source_latitude_invalid", "source_longitude_invalid"]:
            self.assertIn(flag, result.loc[0, "quality_flag"])
        future = self.prepare(self.raw(DATE="2027-01-01T00:00:00"))
        self.assertIn("observation_after_retrieval", future.loc[0, "quality_flag"])

    def test_schema_and_naive_retrieval_rejected(self):
        for raw in [self.raw().iloc[:0], self.raw().drop(columns="STATION"), self.raw().drop(columns=["AA1", "AA2"])]:
            with self.assertRaises(ValueError):
                self.prepare(raw)
        with self.assertRaises(ValueError):
            prepare_noaa_rainfall_interim(self.raw(), "2026-09-18T10:00:00")
        with self.assertRaises(ValueError):
            self.prepare(self.raw().assign(STATION=123))

    def test_report_does_not_assume_hourly_rain_absent(self):
        report = summarize_noaa_rainfall(self.prepare(self.raw(AA1="01,0010,9,1")))
        self.assertNotIn("no_one_hour_precipitation_in_downloaded_sample", report["fitness_limits"])
        self.assertEqual(report["interval_min_counts"], {"60": 1})
