"""从本地官方 CSV 生成水位中间表；每次新建目录，永不覆盖原始/最终数据。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from floodroute.dynamic.water_level import prepare_water_interim, summarize_water

DEFAULT_WATER = ROOT / "data/raw/dynamic/stations/市水务局积涝点水位数据2026091812480193373/市水务局积涝点水位数据_2920001403147.csv"
DEFAULT_STATIONS = ROOT / "data/interim/dynamic/stations_20260918T132952123614+0800/stations_interim.csv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_WATER)
    parser.add_argument("--stations", type=Path, default=DEFAULT_STATIONS)
    args = parser.parse_args()
    paths = {"water": args.input.resolve(), "stations": args.stations.resolve()}
    if not paths["water"].is_relative_to((ROOT / "data/raw/dynamic").resolve()):
        parser.error("水位输入必须位于 data/raw/dynamic 内")
    if not paths["stations"].is_relative_to((ROOT / "data/interim/dynamic").resolve()):
        parser.error("站点输入必须位于 data/interim/dynamic 内")
    originals = {key: path.read_bytes() for key, path in paths.items()}
    inputs = {key: pd.read_csv(io.BytesIO(data), dtype="string", keep_default_na=False, encoding="utf-8-sig")
              for key, data in originals.items()}
    table = prepare_water_interim(inputs["water"], inputs["stations"])
    report = summarize_water(table)
    now = datetime.now(timezone(timedelta(hours=8)))
    folder = ROOT / "data/interim/dynamic" / ("water_level_" + now.strftime("%Y%m%dT%H%M%S%f%z"))
    report.update({
        "processed_at": now.isoformat(),
        "inputs": {key: {"path": paths[key].relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(data).hexdigest()}
                   for key, data in originals.items()},
        "output_path": (folder / "water_level_interim.csv").relative_to(ROOT).as_posix(),
        "official_url": "https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_01403147",
        "history_complete": None,
    })
    for key, path in paths.items():
        if path.read_bytes() != originals[key]:
            raise RuntimeError("处理期间输入发生变化，停止输出")
    folder.mkdir(parents=True, exist_ok=False)
    table.to_csv(folder / "water_level_interim.csv", index=False, encoding="utf-8-sig", mode="x")
    with (folder / "quality_report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    print("水位中间表完成；时间无时区，不能作为最终观测接口。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
