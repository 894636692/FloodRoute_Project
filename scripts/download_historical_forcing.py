"""Download and normalize the account-free NASA POWER event forcing.

The raw API response is preserved byte-for-byte.  The derived table repeats one
coarse regional value over the 4,232 Shenzhen model cells so the frozen v1.2.0
mapping can consume it.  This repetition does not add street-scale information.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
EVENT_DIR = ROOT / "data/historical/shenzhen_2023_0907"
API_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"


def download_power_response(output: Path, *, force: bool = False) -> tuple[bytes, str]:
    """Return the immutable raw response and its exact request URL."""
    params = {
        "parameters": "PRECTOTCORR",
        "community": "AG",
        "longitude": "113.98",
        "latitude": "22.56",
        "start": "20230907",
        "end": "20230909",
        "format": "JSON",
        "time-standard": "UTC",
    }
    request_url = f"{API_URL}?{urlencode(params)}"
    if output.exists() and not force:
        return output.read_bytes(), request_url
    response = requests.get(API_URL, params=params, timeout=90)
    response.raise_for_status()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(response.content)
    return response.content, response.url


def normalize_power_response(raw: bytes, grid_path: Path) -> tuple[pd.DataFrame, dict]:
    """Convert UTC hour-start values to +08:00 preceding-hour accumulations.

    Output columns are compatible with ``map_rainfall``.  ``window_start`` is
    the POWER timestamp and ``timestamp`` is one hour later, because the frozen
    model defines rain_mm as the accumulation during the preceding hour.
    """
    payload = json.loads(raw)
    header = payload["header"]
    if header.get("time_standard") != "UTC":
        raise ValueError("NASA POWER response must be UTC")
    parameter = payload["parameters"]["PRECTOTCORR"]
    if parameter.get("units") != "mm/hour":
        raise ValueError(f"Unexpected unit: {parameter.get('units')}")
    values = payload["properties"]["parameter"]["PRECTOTCORR"]
    rows = []
    for stamp, value in sorted(values.items()):
        start_utc = pd.to_datetime(stamp, format="%Y%m%d%H", utc=True)
        start_local = start_utc.tz_convert("Asia/Shanghai")
        end_local = start_local + pd.Timedelta(hours=1)
        if float(value) < 0:
            continue
        rows.append({"window_start": start_local, "timestamp": end_local, "rain_mm": float(value)})
    hourly = pd.DataFrame(rows)
    grids = pd.read_csv(grid_path, usecols=["grid_id", "lon", "lat"])
    grids["grid_id"] = grids.grid_id.astype(str)
    derived = hourly.merge(grids, how="cross")
    derived["station_id"] = "POWER_REGION_113.98_22.56"
    derived["interval_min"] = 60
    derived["source"] = "NASA POWER MERRA-2 PRECTOTCORR"
    derived["quality_flag"] = "real_historical_coarse_forcing;uniform_study_area_assignment"
    derived["spatial_type"] = "coarse_regional_forcing"
    derived["coordinate_role"] = "model_grid_assignment_not_measurement_location"
    derived["source_record_id"] = derived["window_start"].dt.strftime("POWER_%Y%m%d%H_UTC")
    columns = [
        "station_id", "timestamp", "lon", "lat", "rain_mm", "interval_min", "source",
        "quality_flag", "grid_id", "spatial_type", "coordinate_role",
        "window_start", "source_record_id",
    ]
    derived = derived[columns].sort_values(["timestamp", "grid_id"]).reset_index(drop=True)
    metadata = {
        "data_type": "REAL_HISTORICAL_COARSE_FORCING",
        "product": header.get("title"),
        "api": header.get("api"),
        "source_model": header.get("sources"),
        "parameter": "PRECTOTCORR",
        "unit": "mm/hour",
        "time_resolution": "1 hour",
        "spatial_resolution": "approximately 0.5 degree latitude by 0.625 degree longitude",
        "request_time_standard": "UTC",
        "derived_timezone": "Asia/Shanghai",
        "raw_timestamp_definition": "start of hour",
        "derived_timestamp_definition": "end of preceding one-hour accumulation window",
        "assignment": "single regional POWER point repeated across formal model grid cells",
        "street_scale_truth": False,
        "grid_count": int(grids.grid_id.nunique()),
        "hour_count": int(hourly.timestamp.nunique()),
    }
    return derived, metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="replace the preserved raw response")
    args = parser.parse_args()
    raw_path = EVENT_DIR / "raw/nasa_power_prectotcorr_20230907_20230909_utc.json"
    raw, request_url = download_power_response(raw_path, force=args.force)
    derived, metadata = normalize_power_response(
        raw, ROOT / "data/derived/dynamic/shenzhen_grid/grid_cells.csv"
    )
    derived_path = EVENT_DIR / "rainfall_forcing.parquet"
    derived_path.parent.mkdir(parents=True, exist_ok=True)
    derived.to_parquet(derived_path, index=False, compression="zstd")
    metadata.update(
        {
            "request_url": request_url,
            "raw_path": raw_path.relative_to(ROOT).as_posix(),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "derived_path": derived_path.relative_to(ROOT).as_posix(),
            "derived_sha256": hashlib.sha256(derived_path.read_bytes()).hexdigest(),
            "processing_steps": [
                "parse PRECTOTCORR hourly values",
                "interpret raw timestamps as UTC hour starts",
                "convert to Asia/Shanghai",
                "move timestamp to hour end and preserve window_start",
                "repeat the single regional value over formal model grid IDs without interpolation",
            ],
        }
    )
    metadata_path = EVENT_DIR / "rainfall_forcing_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Raw: {raw_path}")
    print(f"Derived rows: {len(derived):,}; hours: {derived.timestamp.nunique()}; grids: {derived.grid_id.nunique()}")
    print(f"Rain min/max: {derived.rain_mm.min():.2f}/{derived.rain_mm.max():.2f} mm")
    print(f"Metadata: {metadata_path}")


if __name__ == "__main__":
    main()
