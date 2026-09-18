"""Create C-standard dynamic CSV fixtures for B-module self-tests.

This is a local test fixture, not a government raw-interface parser.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "derived" / "dynamic"


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path}")


def main() -> None:
    timestamp = "2026-09-17T15:30:00+08:00"
    retrieved_at = "2026-09-17T15:31:00+08:00"
    stations = [
        {
            "station_id": "rain_center",
            "timestamp": timestamp,
            "lon": 114.055,
            "lat": 22.545,
            "rain_mm": 42.0,
            "source": "fixture",
            "retrieved_at": retrieved_at,
            "quality_flag": "good",
        },
        {
            "station_id": "rain_west",
            "timestamp": timestamp,
            "lon": 114.035,
            "lat": 22.526,
            "rain_mm": 18.0,
            "source": "fixture",
            "retrieved_at": retrieved_at,
            "quality_flag": "good",
        },
    ]
    water = [
        {
            "station_id": "water_center",
            "timestamp": timestamp,
            "lon": 114.055,
            "lat": 22.545,
            "water_level_cm": 38.0,
            "source": "fixture",
            "retrieved_at": retrieved_at,
            "quality_flag": "good",
        },
        {
            "station_id": "water_east",
            "timestamp": timestamp,
            "lon": 114.074,
            "lat": 22.526,
            "water_level_cm": 16.0,
            "source": "fixture",
            "retrieved_at": retrieved_at,
            "quality_flag": "good",
        },
    ]
    write_rows(OUT_DIR / "rainfall.csv", stations)
    write_rows(OUT_DIR / "water_level.csv", water)


if __name__ == "__main__":
    main()

