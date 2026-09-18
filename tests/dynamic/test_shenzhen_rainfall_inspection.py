"""合成检查用例只在内存存在，不写入真实数据目录。"""
from pathlib import Path
import sys
import unittest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from inspect_shenzhen_rainfall_download import inspect_tables, RAIN, TIMES, BOUNDS


class ShenzhenRainfallInspectionTests(unittest.TestCase):
    def frames(self):
        row = {column: "0" for column in RAIN}
        row.update({column: "\t2026-09-18 00:40:00" for column in TIMES})
        row.update({"格网ID": "001", "记录编号": "01", "预报时效（小时）": "0", "预报级别": "0", "Tracer1小时累计降雨量预报": "-1"})
        grid = dict(zip(BOUNDS, ["114", "22", "114.01", "22.01"]))
        grid["格网ID（唯一）"] = "001"
        return pd.DataFrame([row], dtype="string"), pd.DataFrame([grid], dtype="string")

    def test_match_preserves_raw_and_does_not_claim_final_validity(self):
        data, grids = self.frames()
        original = data.copy(deep=True)
        result = inspect_tables(data, grids)
        pd.testing.assert_frame_equal(original, data)
        self.assertEqual(result["matched_data_rows"], 1)
        self.assertTrue(result["safe_many_to_one_join"])
        self.assertEqual(result["standard_interface_status"], "blocked")
        self.assertEqual(result["source_times"]["预报时间"]["min_without_timezone"], "2026-09-18 00:40:00")
        self.assertEqual(result["rainfall_columns"]["1小时累计降雨量（毫米）"]["interval_min_from_column_label"], 60)
        self.assertEqual(result["rainfall_columns"]["Tracer1小时累计降雨量预报"]["negative_count"], 1)

    def test_duplicate_registry_and_unmatched_data_do_not_expand_join(self):
        data, grids = self.frames()
        data = pd.concat([data, data], ignore_index=True)
        data.loc[1, "格网ID"] = "999"
        result = inspect_tables(data, pd.concat([grids, grids], ignore_index=True))
        self.assertFalse(result["safe_many_to_one_join"])
        self.assertEqual(result["grid_duplicate_id_rows"], 2)
        self.assertEqual(result["unmatched_data_rows"], 1)
        self.assertEqual(result["data_rows"], 2)
        self.assertEqual(result["raw_rows_removed"], 0)

    def test_invalid_time_bounds_and_values_are_reported(self):
        data, grids = self.frames()
        data.loc[0, "预报时间"] = "bad"
        data.loc[0, "1小时累计降雨量（毫米）"] = "inf"
        grids.loc[0, BOUNDS[0]] = ""
        result = inspect_tables(data, grids)
        self.assertEqual(result["source_times"]["预报时间"]["invalid_or_missing"], 1)
        self.assertEqual(result["invalid_grid_bounds_count"], 1)
        self.assertEqual(result["per_source_time_coverage"], [])
        self.assertEqual(result["rainfall_columns"]["1小时累计降雨量（毫米）"]["missing_or_nonfinite_count"], 1)

    def test_duplicate_grid_time_and_missing_schema(self):
        data, grids = self.frames()
        result = inspect_tables(pd.concat([data, data], ignore_index=True), grids)
        self.assertEqual(result["duplicate_grid_source_time_affected_rows"], 2)
        with self.assertRaises(ValueError):
            inspect_tables(data.drop(columns="预报时间"), grids)
