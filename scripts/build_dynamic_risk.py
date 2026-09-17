from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from osgeo import gdal


ROOT = Path(r"D:\LaotuZhBi\laotu-data")
RAW = ROOT / "data" / "raw" / "shenzhen_open_data"
STATIC = ROOT / "data" / "processed" / "static_risk"
DYNAMIC = ROOT / "data" / "processed" / "dynamic_risk"
DYNAMIC.mkdir(parents=True, exist_ok=True)

NODATA = -9999.0
HEAVY_RAIN_MM_H = 30.0
DYNAMIC_WEIGHT = 0.45


def read_raster(path: Path):
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open raster: {path}")
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    return arr, ds


def write_float_raster(path: Path, template: gdal.Dataset, arr: np.ndarray) -> None:
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(
        str(path),
        template.RasterXSize,
        template.RasterYSize,
        1,
        gdal.GDT_Float32,
        options=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"],
    )
    ds.SetGeoTransform(template.GetGeoTransform())
    ds.SetProjection(template.GetProjection())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(NODATA)
    band.WriteArray(np.where(np.isfinite(arr), arr, NODATA).astype(np.float32))
    band.FlushCache()
    ds.FlushCache()
    ds = None


def write_rgb_raster(path: Path, template: gdal.Dataset, risk: np.ndarray) -> None:
    valid = np.isfinite(risk)
    arr = np.clip(risk, 0, 1)
    r = np.zeros(arr.shape, dtype=np.uint8)
    g = np.zeros(arr.shape, dtype=np.uint8)
    b = np.zeros(arr.shape, dtype=np.uint8)
    low = arr <= 0.5
    high = arr > 0.5
    r[low] = (26 + (255 - 26) * (arr[low] / 0.5)).astype(np.uint8)
    g[low] = (152 + (255 - 152) * (arr[low] / 0.5)).astype(np.uint8)
    b[low] = (80 + (191 - 80) * (arr[low] / 0.5)).astype(np.uint8)
    r[high] = (255 + (215 - 255) * ((arr[high] - 0.5) / 0.5)).astype(np.uint8)
    g[high] = (255 + (48 - 255) * ((arr[high] - 0.5) / 0.5)).astype(np.uint8)
    b[high] = (191 + (39 - 191) * ((arr[high] - 0.5) / 0.5)).astype(np.uint8)
    r[~valid] = 0
    g[~valid] = 0
    b[~valid] = 0

    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(
        str(path),
        template.RasterXSize,
        template.RasterYSize,
        3,
        gdal.GDT_Byte,
        options=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"],
    )
    ds.SetGeoTransform(template.GetGeoTransform())
    ds.SetProjection(template.GetProjection())
    for i, band_arr in enumerate([r, g, b], start=1):
        band = ds.GetRasterBand(i)
        band.WriteArray(band_arr)
        band.SetNoDataValue(0)
    ds.FlushCache()
    ds = None


def load_open_meteo_events() -> list[dict]:
    data = json.loads((RAW / "open_meteo_shenzhen_center_precip_2026-09-17.json").read_text(encoding="utf-8-sig"))
    times = data["hourly"]["time"]
    precip = data["hourly"]["precipitation"]
    events = []
    for time, rain in zip(times, precip):
        if float(rain) > 0:
            events.append({"scenario": "observed", "time": time, "precip_mm_h": float(rain)})
    if not events:
        current = data.get("current", {})
        events.append({"scenario": "observed", "time": current.get("time", "current"), "precip_mm_h": float(current.get("precipitation") or 0)})

    # Keep observed output compact, but include the wettest hour.
    events = sorted(events, key=lambda x: x["precip_mm_h"], reverse=True)[:3]
    events.sort(key=lambda x: x["time"])
    events.append({"scenario": "stress_30mm", "time": "stress_30mm_per_h", "precip_mm_h": 30.0})
    return events


def safe_name(event: dict) -> str:
    return f"{event['scenario']}_{event['time'].replace(':', '').replace('-', '').replace('T', '_')}"


def main() -> None:
    static_risk, template = read_raster(STATIC / "static_risk.tif")
    elevation_risk, _ = read_raster(STATIC / "risk_elevation.tif")
    valid = np.isfinite(static_risk) & np.isfinite(elevation_risk) & (static_risk != NODATA) & (elevation_risk != NODATA)
    events = load_open_meteo_events()
    rows = []

    for event in events:
        rain_norm = min(max(event["precip_mm_h"] / HEAVY_RAIN_MM_H, 0.0), 1.0)
        # Rainfall impact is spatially amplified in low-lying areas.
        rain_risk = np.full(static_risk.shape, np.nan, dtype=np.float32)
        dynamic_risk = np.full(static_risk.shape, np.nan, dtype=np.float32)
        rain_risk[valid] = rain_norm * elevation_risk[valid]
        dynamic_risk[valid] = np.clip(static_risk[valid] + DYNAMIC_WEIGHT * rain_risk[valid], 0, 1)

        name = safe_name(event)
        rain_path = DYNAMIC / f"rain_risk_{name}.tif"
        risk_path = DYNAMIC / f"dynamic_risk_{name}.tif"
        rgb_path = DYNAMIC / f"dynamic_risk_{name}_rgb.tif"
        write_float_raster(rain_path, template, rain_risk)
        write_float_raster(risk_path, template, dynamic_risk)
        write_rgb_raster(rgb_path, template, dynamic_risk)

        vals = dynamic_risk[np.isfinite(dynamic_risk)]
        rows.append(
            {
                "scenario": event["scenario"],
                "time": event["time"],
                "precip_mm_h": event["precip_mm_h"],
                "rain_norm": round(rain_norm, 4),
                "dynamic_weight": DYNAMIC_WEIGHT,
                "dynamic_risk_path": str(risk_path),
                "dynamic_risk_rgb_path": str(rgb_path),
                "rain_risk_path": str(rain_path),
                "mean_dynamic_risk": round(float(np.mean(vals)), 4),
                "max_dynamic_risk": round(float(np.max(vals)), 4),
            }
        )

    template = None
    inventory = DYNAMIC / "dynamic_risk_inventory.csv"
    with inventory.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(inventory)


if __name__ == "__main__":
    gdal.UseExceptions()
    main()
