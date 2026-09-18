from pathlib import Path
import sys
import unittest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from floodroute.dynamic.shenzhen_rainfall import normalize_shenzhen_rainfall, RAIN, BOUNDS


class ShenzhenRainfallTests(unittest.TestCase):
    def setUp(self):
        self.metadata = dict(crs="EPSG:4326", timezone="Asia/Shanghai", timestamp_field="预报时间",
                             window_direction="preceding", time_definition_provenance="user_confirmation", retrieved_at=None)
        row = {field: "1.5" for field in RAIN.values()}
        row.update({"格网ID": "001", "记录编号": "0002", "预报时间": "\t2026-09-18 00:40:00",
                    "发布时间": "2026-09-18 00:50:00", "入库时间": "2026-09-18 01:00:00",
                    "预报时效（小时）": "0", "预报级别": "0"})
        self.data = pd.DataFrame([row], dtype="string")
        grid = dict(zip(BOUNDS, ["114", "22.5", "114.01", "22.51"]))
        grid["格网ID（唯一）"] = "001"
        self.grids = pd.DataFrame([grid], dtype="string")

    def run_normalize(self, data=None, grids=None):
        return normalize_shenzhen_rainfall(self.data if data is None else data, self.grids if grids is None else grids, self.metadata)

    def test_time_anchor_midnight_window_and_grid_center(self):
        interim, hourly, cells = self.run_normalize()
        row = hourly.iloc[0]
        self.assertEqual(row.timestamp, "2026-09-18T00:40:00+08:00")
        self.assertEqual(row.window_start, "2026-09-17T23:40:00+08:00")
        self.assertEqual(row.station_id, "SZ_GRID_001")
        self.assertEqual(row.source_record_id, "0002")
        self.assertAlmostEqual(row.lon, 114.005)
        self.assertAlmostEqual(row.lat, 22.505)
        self.assertEqual(row.interval_min, 60)
        self.assertTrue(pd.isna(row.retrieved_at))
        self.assertEqual(cells.iloc[0].coordinate_role, "grid_center_not_station")

    def test_original_fields_and_all_rain_periods_preserved(self):
        before = self.data.copy(deep=True)
        interim, hourly, _ = self.run_normalize()
        pd.testing.assert_frame_equal(before, self.data)
        pd.testing.assert_frame_equal(interim[before.columns], before)
        for hours in RAIN:
            self.assertEqual(interim.iloc[0][f"rain_{hours}h_mm"], 1.5)
        self.assertEqual(hourly.iloc[0].rain_mm, 1.5)

    def test_bad_data_retained_and_flagged(self):
        data = self.data.copy()
        data.loc[0, "1小时累计降雨量（毫米）"] = "-1"
        data.loc[0, "2小时累计降雨量（毫米）"] = "inf"
        data.loc[0, "预报时间"] = "bad"
        data.loc[0, "格网ID"] = "999"
        data.loc[0, "预报时效（小时）"] = "1"
        interim, hourly, _ = self.run_normalize(data)
        self.assertEqual(len(hourly), 1)
        self.assertEqual(hourly.iloc[0].rain_mm, -1)
        self.assertTrue(pd.isna(interim.iloc[0].rain_2h_mm))
        for flag in ["rain_1h_negative", "rain_2h_missing_or_invalid", "source_time_invalid", "grid_not_found", "nonzero_or_invalid_forecast_lead"]:
            self.assertIn(flag, hourly.iloc[0].quality_flag)

    def test_duplicate_observations_retained_but_duplicate_registry_rejected(self):
        _, hourly, _ = self.run_normalize(pd.concat([self.data, self.data], ignore_index=True))
        self.assertEqual(len(hourly), 2)
        self.assertTrue(hourly.quality_flag.str.contains("duplicate_grid_timestamp").all())
        with self.assertRaises(ValueError):
            self.run_normalize(grids=pd.concat([self.grids, self.grids], ignore_index=True))

    def test_missing_metadata_or_invalid_schema_rejected(self):
        with self.assertRaises(ValueError):
            self.run_normalize(data=self.data.drop(columns="预报时间"))
        self.metadata["timezone"] = "UTC"
        with self.assertRaises(ValueError):
            self.run_normalize()

    def test_bad_grid_bounds_never_produce_plausible_center(self):
        grids = self.grids.copy()
        grids.loc[0, BOUNDS[0]] = "200"
        _, hourly, cells = self.run_normalize(grids=grids)
        self.assertTrue(hourly.lon.isna().all())
        self.assertIn("invalid_grid_bounds", cells.iloc[0].quality_flag)
