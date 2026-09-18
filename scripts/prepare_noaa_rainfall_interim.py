"""读取已下载 NOAA ISD CSV 和下载回执，生成候选降雨中间表及质量报告。"""

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
from floodroute.dynamic.rainfall import prepare_noaa_rainfall_interim, summarize_noaa_rainfall

DEFAULT_FOLDER = ROOT / "data/raw/dynamic/rainfall/noaa_isd_20260918T135237268402+0800"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_FOLDER / "59493099999_2025.csv")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_FOLDER / "download_receipt.json")
    args = parser.parse_args()
    raw_path, receipt_path = args.input.resolve(), args.receipt.resolve()
    for path in [raw_path, receipt_path]:
        if not path.is_relative_to((ROOT / "data/raw/dynamic/rainfall").resolve()):
            parser.error("输入及回执须位于 data/raw/dynamic/rainfall 内")
    original, receipt_bytes = raw_path.read_bytes(), receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    digest = hashlib.sha256(original).hexdigest()
    if digest != receipt["sha256"]:
        raise ValueError("下载回执与原文件哈希不符，停止解析")
    raw = pd.read_csv(io.BytesIO(original), dtype="string", keep_default_na=False, encoding="utf-8-sig")
    table = prepare_noaa_rainfall_interim(raw, receipt["retrieved_at"])
    report = summarize_noaa_rainfall(table)
    now = datetime.now(timezone(timedelta(hours=8)))
    folder = ROOT / "data/interim/dynamic" / ("rainfall_noaa_" + now.strftime("%Y%m%dT%H%M%S%f%z"))
    report.update(processed_at=now.isoformat(), retrieved_at=receipt["retrieved_at"],
                  source_url=receipt["source_url"], raw_path=raw_path.relative_to(ROOT).as_posix(),
                  raw_sha256=digest, receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
                  output_path=(folder / "rainfall_interim.csv").relative_to(ROOT).as_posix())
    if raw_path.read_bytes() != original or receipt_path.read_bytes() != receipt_bytes:
        raise RuntimeError("处理期间输入发生变化")
    folder.mkdir(parents=True, exist_ok=False)
    table.to_csv(folder / "rainfall_interim.csv", index=False, encoding="utf-8-sig", mode="x")
    with (folder / "quality_report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
