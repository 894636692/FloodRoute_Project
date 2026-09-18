"""只读官方站点 CSV，将中间表和质量报告保存到新建的运行目录。"""

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
from floodroute.dynamic.stations import prepare_station_interim, summarize_stations

DEFAULT_INPUT = ROOT / "data/raw/dynamic/stations/市水务局测站基本信息表20260918114804559062/市水务局测站基本信息表_2920001400987.csv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()
    raw_path = args.input.resolve()
    if not raw_path.is_relative_to((ROOT / "data/raw/dynamic/stations").resolve()):
        parser.error("输入必须位于 data/raw/dynamic/stations 中")
    original = raw_path.read_bytes()
    # dtype='string' 保留前导零；关闭默认 NA 识别，避免把文本编码当作空值。
    raw = pd.read_csv(io.BytesIO(original), encoding="utf-8-sig", dtype="string", keep_default_na=False)
    table = prepare_station_interim(raw)
    report = summarize_stations(table)
    now = datetime.now(timezone(timedelta(hours=8)))
    run_dir = ROOT / "data/interim/dynamic" / ("stations_" + now.strftime("%Y%m%dT%H%M%S%f%z"))
    report.update({
        "processed_at": now.isoformat(),  # 程序处理时间，不是下载或观测时间。
        "raw_path": raw_path.relative_to(ROOT).as_posix(),
        "raw_sha256": hashlib.sha256(original).hexdigest(),
        "output_path": (run_dir / "stations_interim.csv").relative_to(ROOT).as_posix(),
        "official_url": "https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_01400987",
    })
    if raw_path.read_bytes() != original:
        raise RuntimeError("读取期间原始文件发生变化，停止输出")
    run_dir.mkdir(parents=True, exist_ok=False)
    table.to_csv(run_dir / "stations_interim.csv", index=False, encoding="utf-8-sig", mode="x")
    with (run_dir / "quality_report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("中间表整理完成；最终 stations.csv 仍因缺坐标而 blocked。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
