from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
from osgeo import gdal


ROOT = Path(r"D:\LaotuZhBi\laotu-data")
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
OUT = PROCESSED / "static_risk"
OUT.mkdir(parents=True, exist_ok=True)

# Current first-stage validation area used by the downloaded OSM sample:
# min_lon, min_lat, max_lon, max_lat
BBOX = (113.88, 22.50, 114.08, 22.62)
PIXEL_SIZE = 0.0002777777777777778  # about 30 m in EPSG:4326 DEM tiles
NODATA = -9999.0

WEIGHTS = {
    "elevation": 0.45,
    "slope": 0.25,
    "landcover": 0.30,
}

# ESA WorldCover class risk values, first explainable version.
# 10 Tree cover, 20 Shrubland, 30 Grassland, 40 Cropland, 50 Built-up,
# 60 Bare/sparse vegetation, 70 Snow/ice, 80 Permanent water bodies,
# 90 Herbaceous wetland, 95 Mangroves, 100 Moss/lichen.
LANDCOVER_RISK = {
    10: 0.20,
    20: 0.35,
    30: 0.35,
    40: 0.55,
    50: 0.85,
    60: 0.60,
    70: 0.20,
    80: 1.00,
    90: 0.80,
    95: 0.70,
    100: 0.30,
}


def warp_raster(inputs: list[Path], output: Path, *, resample: str, dtype=None, nodata=None) -> None:
    options = gdal.WarpOptions(
        format="GTiff",
        outputBounds=BBOX,
        outputBoundsSRS="EPSG:4326",
        dstSRS="EPSG:4326",
        xRes=PIXEL_SIZE,
        yRes=PIXEL_SIZE,
        resampleAlg=resample,
        multithread=True,
        creationOptions=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"],
        outputType=dtype,
        dstNodata=nodata,
    )
    ds = gdal.Warp(str(output), [str(p) for p in inputs], options=options)
    if ds is None:
        raise RuntimeError(f"gdal.Warp failed for {output}")
    ds.FlushCache()
    ds = None


def read_band(path: Path) -> tuple[np.ndarray, gdal.Dataset]:
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open raster: {path}")
    arr = ds.GetRasterBand(1).ReadAsArray()
    return arr, ds


def write_float_raster(path: Path, template: gdal.Dataset, arr: np.ndarray, nodata: float = NODATA) -> None:
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
    band.SetNoDataValue(nodata)
    out = np.where(np.isfinite(arr), arr, nodata).astype(np.float32)
    band.WriteArray(out)
    band.FlushCache()
    ds.FlushCache()
    ds = None


def normalized_inverse(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    if valid.sum() == 0:
        return out
    lo, hi = np.nanpercentile(values[valid], [2, 98])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return out
    out[valid] = np.clip((hi - values[valid]) / (hi - lo), 0, 1)
    return out


def slope_risk_from_slope_degrees(slope: np.ndarray, valid: np.ndarray) -> np.ndarray:
    out = np.full(slope.shape, np.nan, dtype=np.float32)
    # Low, flat areas are more prone to ponding. Slopes above 15 deg get low risk.
    out[valid] = 1.0 - np.clip(slope[valid] / 15.0, 0, 1)
    return out


def landcover_risk_from_classes(classes: np.ndarray, valid: np.ndarray) -> np.ndarray:
    out = np.full(classes.shape, np.nan, dtype=np.float32)
    out[valid] = 0.50
    for cls, risk in LANDCOVER_RISK.items():
        out[classes == cls] = risk
    return out


def sample_raster_along_line(coords: list[list[float]], arr: np.ndarray, geotransform) -> list[float]:
    inv = gdal.InvGeoTransform(geotransform)
    if inv is None:
        raise RuntimeError("Cannot invert raster geotransform")
    samples: list[float] = []
    if len(coords) < 2:
        return samples

    step = PIXEL_SIZE
    height, width = arr.shape

    def add_sample(x: float, y: float) -> None:
        px = int(inv[0] + inv[1] * x + inv[2] * y)
        py = int(inv[3] + inv[4] * x + inv[5] * y)
        if 0 <= px < width and 0 <= py < height:
            val = float(arr[py, px])
            if np.isfinite(val):
                samples.append(val)

    for a, b in zip(coords[:-1], coords[1:]):
        x1, y1 = a
        x2, y2 = b
        dist = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(math.ceil(dist / step)))
        for i in range(n + 1):
            t = i / n
            add_sample(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
    return samples


def build_roads_risk(static_risk: np.ndarray, dem_ds: gdal.Dataset) -> tuple[Path, int]:
    roads_path = PROCESSED / "osm" / "roads.geojson"
    output = OUT / "roads_static_risk.geojson"
    data = json.loads(roads_path.read_text(encoding="utf-8"))
    out_features = []
    gt = dem_ds.GetGeoTransform()

    for feature in data.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates") or []
        vals = sample_raster_along_line(coords, static_risk, gt)
        props = dict(feature.get("properties") or {})
        if vals:
            arr = np.asarray(vals, dtype=np.float32)
            props["risk_mean"] = round(float(np.mean(arr)), 4)
            props["risk_max"] = round(float(np.max(arr)), 4)
            props["risk_p90"] = round(float(np.percentile(arr, 90)), 4)
            props["risk_samples"] = int(arr.size)
        else:
            props["risk_mean"] = None
            props["risk_max"] = None
            props["risk_p90"] = None
            props["risk_samples"] = 0
        out_features.append({"type": "Feature", "geometry": geom, "properties": props})

    output.write_text(
        json.dumps({"type": "FeatureCollection", "features": out_features}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return output, len(out_features)


def write_inventory(rows: list[dict[str, object]]) -> Path:
    path = OUT / "static_risk_inventory.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "path", "type", "count_or_size", "note"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> None:
    dem_clip = OUT / "dem_clip.tif"
    wc_clip = OUT / "worldcover_clip_30m.tif"
    slope_clip = OUT / "slope_degrees.tif"

    warp_raster(
        sorted((RAW / "dem").glob("Copernicus_DSM_COG_10_N22_00_E*.tif")),
        dem_clip,
        resample="bilinear",
        dtype=gdal.GDT_Float32,
        nodata=NODATA,
    )
    warp_raster(
        sorted((RAW / "worldcover").glob("ESA_WorldCover_10m_2021_v200_*.tif")),
        wc_clip,
        resample="near",
        dtype=gdal.GDT_Byte,
        nodata=0,
    )

    # DEM is in EPSG:4326 degrees. Scale converts horizontal degree spacing to meters
    # for a first-pass slope product.
    slope_ds = gdal.DEMProcessing(
        str(slope_clip),
        str(dem_clip),
        "slope",
        format="GTiff",
        computeEdges=True,
        scale=111120.0,
        creationOptions=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"],
    )
    if slope_ds is None:
        raise RuntimeError("gdal.DEMProcessing slope failed")
    slope_ds.FlushCache()
    slope_ds = None

    dem, dem_ds = read_band(dem_clip)
    slope, _ = read_band(slope_clip)
    wc, _ = read_band(wc_clip)

    dem_valid = np.isfinite(dem) & (dem != NODATA)
    slope_valid = np.isfinite(slope) & (slope >= 0)
    wc_valid = wc != 0
    valid = dem_valid & slope_valid & wc_valid

    elevation_risk = normalized_inverse(dem.astype(np.float32), valid)
    slope_risk = slope_risk_from_slope_degrees(slope.astype(np.float32), valid)
    landcover_risk = landcover_risk_from_classes(wc, valid)

    static_risk = (
        WEIGHTS["elevation"] * elevation_risk
        + WEIGHTS["slope"] * slope_risk
        + WEIGHTS["landcover"] * landcover_risk
    )
    static_risk[~valid] = np.nan
    static_risk = np.clip(static_risk, 0, 1)

    elevation_risk_path = OUT / "risk_elevation.tif"
    slope_risk_path = OUT / "risk_slope.tif"
    landcover_risk_path = OUT / "risk_landcover.tif"
    static_risk_path = OUT / "static_risk.tif"
    write_float_raster(elevation_risk_path, dem_ds, elevation_risk)
    write_float_raster(slope_risk_path, dem_ds, slope_risk)
    write_float_raster(landcover_risk_path, dem_ds, landcover_risk)
    write_float_raster(static_risk_path, dem_ds, static_risk)

    roads_risk_path, road_count = build_roads_risk(static_risk, dem_ds)
    dem_ds = None

    valid_values = static_risk[np.isfinite(static_risk)]
    rows = [
        {"name": "dem_clip", "path": str(dem_clip), "type": "Raster", "count_or_size": dem_clip.stat().st_size, "note": "研究区 DEM 裁剪"},
        {"name": "worldcover_clip_30m", "path": str(wc_clip), "type": "Raster", "count_or_size": wc_clip.stat().st_size, "note": "WorldCover 重采样到 DEM 30m 网格"},
        {"name": "slope_degrees", "path": str(slope_clip), "type": "Raster", "count_or_size": slope_clip.stat().st_size, "note": "由 DEM 生成的坡度"},
        {"name": "risk_elevation", "path": str(elevation_risk_path), "type": "Raster", "count_or_size": elevation_risk_path.stat().st_size, "note": "低高程风险，0-1"},
        {"name": "risk_slope", "path": str(slope_risk_path), "type": "Raster", "count_or_size": slope_risk_path.stat().st_size, "note": "低坡度风险，0-1"},
        {"name": "risk_landcover", "path": str(landcover_risk_path), "type": "Raster", "count_or_size": landcover_risk_path.stat().st_size, "note": "土地覆盖风险，0-1"},
        {
            "name": "static_risk",
            "path": str(static_risk_path),
            "type": "Raster",
            "count_or_size": static_risk_path.stat().st_size,
            "note": f"静态综合风险，mean={float(np.mean(valid_values)):.4f}, min={float(np.min(valid_values)):.4f}, max={float(np.max(valid_values)):.4f}",
        },
        {"name": "roads_static_risk", "path": str(roads_risk_path), "type": "LineString GeoJSON", "count_or_size": road_count, "note": "每条道路含 risk_mean/risk_max/risk_p90"},
    ]
    inv = write_inventory(rows)
    print("Static risk complete")
    print(f"bbox={BBOX}")
    print(f"weights={WEIGHTS}")
    print(f"roads={road_count}")
    print(f"inventory={inv}")


if __name__ == "__main__":
    gdal.UseExceptions()
    main()
