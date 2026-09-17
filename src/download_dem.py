"""Step 5: read a real Copernicus GLO-30 window, clip it and inspect heights."""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

project_dir = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(project_dir / "work" / "matplotlib"))

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.transform import array_bounds
from rasterio.windows import Window, from_bounds
from shapely.geometry import box, mapping

# This public object was verified in the AWS open-data bucket listing.
tile = "Copernicus_DSM_COG_10_N22_00_E114_00_DEM"
source_url = f"https://copernicus-dem-30m.s3.amazonaws.com/{tile}/{tile}.tif"
raw_dir = project_dir / "data" / "raw" / "dem"
processed_dir = project_dir / "data" / "processed" / "dem"
maps_dir = project_dir / "outputs" / "maps"
for directory in [raw_dir, processed_dir, maps_dir]:
    directory.mkdir(parents=True, exist_ok=True)
raw_path = raw_dir / "copernicus_glo30_source_window.tif"
source_record = raw_dir / "copernicus_glo30_source.json"
clip_path = processed_dir / "dem_clip.tif"

# 1. Use the same saved study boundary as OSM.
area = gpd.read_file(project_dir / "study_area.geojson")
assert len(area) == 1 and area.geometry.is_valid.all()
assert area.crs is not None and area.crs.to_epsg() == 4326
polygon = area.geometry.iloc[0]
print("Study area CRS:", area.crs, flush=True)
print("Source:", source_url, flush=True)

# 2. Read native-resolution pixels for a small rectangular window only.
# COG servers transfer the TIFF blocks intersecting this window, not just
# individual pixels. The saved file is a source subset, NOT the full tile.
if not raw_path.exists():
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT=60):
        with rasterio.open(source_url) as src:
            print("Source width / height:", src.width, src.height, flush=True)
            print("Source CRS:", src.crs, flush=True)
            print("Source pixel size (degrees):", src.res, flush=True)
            print("Source NoData:", src.nodata, flush=True)
            print("Source bounds:", src.bounds, flush=True)
            assert src.crs == area.crs, "Unexpected CRS: stop before clipping"
            assert box(*src.bounds).covers(polygon), "Test area is outside this tile"
            window_float = from_bounds(*area.total_bounds, transform=src.transform)
            col0 = max(0, math.floor(window_float.col_off) - 1)
            row0 = max(0, math.floor(window_float.row_off) - 1)
            col1 = min(src.width, math.ceil(window_float.col_off + window_float.width) + 1)
            row1 = min(src.height, math.ceil(window_float.row_off + window_float.height) + 1)
            window = Window(col0, row0, col1 - col0, row1 - row0)
            pixels = src.read(1, window=window)
            validity = src.read_masks(1, window=window)
            profile = dict(
                driver="GTiff", height=pixels.shape[0], width=pixels.shape[1],
                count=1, dtype=pixels.dtype, crs=src.crs,
                transform=src.window_transform(window), nodata=src.nodata,
                compress="deflate",
            )
            record = {
                "product": "Copernicus DEM GLO-30 Public (DSM)",
                "source_url": source_url,
                "provider_documentation": "https://copernicus-dem-30m.s3.amazonaws.com/readme.html",
                "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                "source_width": src.width, "source_height": src.height,
                "source_crs": str(src.crs), "source_resolution_degrees": list(src.res),
                "source_nodata": src.nodata, "source_bounds": list(src.bounds),
                "source_tags": src.tags(),
                "window_col_row_width_height": [col0, row0, col1 - col0, row1 - row0],
                "study_bbox": area.total_bounds.tolist(),
                "vertical_reference": "EGM2008; heights in metres",
                "processing": "Native pixel window only; no resampling or reprojection; source validity mask retained.",
                "attribution": "Copernicus WorldDEM-30; DLR 2010-2014; Airbus Defence and Space 2014-2018; provided by EU and ESA",
            }
            with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
                with rasterio.open(raw_path, "w", **profile) as dst:
                    dst.write(pixels, 1)
                    dst.write_mask(validity)
                    dst.update_tags(**src.tags())
            source_record.write_text(json.dumps(record, indent=2), encoding="utf-8")
else:
    print("Reusing saved source window; it will not be modified.", flush=True)
    if not source_record.exists():
        raise RuntimeError("Source metadata is missing. Stop and inspect the saved files.")

# 3. Clip by the polygon, keeping the original grid and pixel values.
# The raster stays rectangular; pixels outside the polygon become NoData.
with rasterio.open(raw_path) as src:
    assert src.crs == area.crs
    assert box(*src.bounds).covers(polygon), "Saved window does not cover the test area"
    print("Local source shape (rows, columns):", src.shape)
    print("Local source CRS / pixel size / NoData:", src.crs, src.res, src.nodata)
    print("Local source bounds:", src.bounds)
    clipped, transform = mask(src, [mapping(polygon)], crop=True, filled=False)
    dem = np.ma.masked_invalid(clipped[0])
    inside = geometry_mask(
        [mapping(polygon)], out_shape=dem.shape, transform=transform, invert=True,
    )
    missing_inside = inside & np.ma.getmaskarray(dem)
    inside_count = int(inside.sum())
    assert inside_count > 0 and dem.count() > 0, "No valid test-area pixels"
    nodata = -9999.0
    assert not np.any(dem.compressed() == nodata), "Output NoData collides with real values"
    profile = src.profile.copy()
    profile.update(height=dem.shape[0], width=dem.shape[1], transform=transform,
                   nodata=nodata, dtype="float32")
    with rasterio.open(clip_path, "w", **profile) as dst:
        dst.write(dem.filled(nodata).astype("float32"), 1)

# 4. Reopen the saved result and inspect only valid elevation pixels.
with rasterio.open(clip_path) as src:
    saved = src.read(1, masked=True)
    assert saved.shape == dem.shape
    assert np.array_equal(np.ma.getmaskarray(saved), np.ma.getmaskarray(dem))
    assert np.array_equal(saved.compressed(), dem.compressed())
    print("\n--- DEM checks ---")
    print("Width / height:", src.width, src.height)
    print("Array shape (rows, columns):", saved.shape)
    print("Data type:", saved.dtype)
    print("CRS:", src.crs)
    print("Pixel size (degrees):", src.res)
    print("Output NoData:", src.nodata)
    print("Output bounds:", src.bounds)
    print("Elevation min / max (m):", float(saved.min()), float(saved.max()))
    print("Elevation percentiles 1 / 50 / 99 (m):", np.percentile(saved.compressed(), [1, 50, 99]))
    print("Valid pixels:", saved.count())
    print("Missing pixels INSIDE boundary:", int(missing_inside.sum()), "/", inside_count)
    print("Boundary handling: pixel-centre inclusion; no resampling or reprojection.")
    west, south, east, north = array_bounds(src.height, src.width, src.transform)

# 5. Plot the saved DEM, with its true geographic extent and an explicit legend.
fig, ax = plt.subplots(figsize=(9, 9))
cmap = plt.get_cmap("viridis").copy()
cmap.set_bad("white")
im = ax.imshow(saved, extent=(west, east, south, north), origin="upper",
               cmap=cmap, interpolation="nearest")
area.boundary.plot(ax=ax, color="#d1493f", linewidth=1.1)
ax.set_title("Shenzhen test area - Copernicus GLO-30 (DSM)")
ax.set_xlabel("Longitude (degrees; WGS 84)")
ax.set_ylabel("Latitude (degrees; WGS 84)")
ax.ticklabel_format(useOffset=False, style="plain")
fig.colorbar(im, ax=ax, shrink=0.75, label="Surface elevation (m; EGM2008)")
fig.text(0.5, 0.02, "Copernicus GLO-30 via AWS Open Data | DLR / Airbus, EU / ESA\nRed: test boundary | White: masked pixels", ha="center", fontsize=8)
fig.tight_layout(rect=(0, 0.05, 1, 1))
map_path = maps_dir / "dem_test.png"
fig.savefig(map_path, dpi=200)
plt.close(fig)
print("Source window:", raw_path)
print("Clipped DEM:", clip_path)
print("Map:", map_path)
if missing_inside.any():
    raise RuntimeError("DEM has missing pixels inside the boundary. Inspect before continuing.")
print("DEM technical checks passed. Inspect min/max and PNG before continuing.")
