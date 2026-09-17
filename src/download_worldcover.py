"""Step 6: acquire and plot real ESA WorldCover 2021 v200 categories."""

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
from matplotlib.colors import ListedColormap, NoNorm
from matplotlib.patches import Patch
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.transform import array_bounds
from rasterio.windows import Window, from_bounds
from shapely.geometry import box, mapping

# Official class IDs are preserved in the TIFF. They are not quantities.
labels = {
    10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland",
    50: "Built-up", 60: "Bare / sparse vegetation", 70: "Snow and ice",
    80: "Permanent water bodies", 90: "Herbaceous wetland",
    95: "Mangroves", 100: "Moss and lichen",
}
source_url = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_N21E114_Map.tif"
)
attribution = (
    "ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021)\n"
    "processed by ESA WorldCover consortium"
)
raw_dir = project_dir / "data" / "raw" / "worldcover"
processed_dir = project_dir / "data" / "processed" / "worldcover"
maps_dir = project_dir / "outputs" / "maps"
for directory in [raw_dir, processed_dir, maps_dir]:
    directory.mkdir(parents=True, exist_ok=True)
raw_path = raw_dir / "worldcover_2021_v200_source_window.tif"
source_record = raw_dir / "worldcover_2021_v200_source.json"
clip_path = processed_dir / "worldcover_clip.tif"

# 1. The same polygon used for OSM and DEM; no new bbox is typed here.
area = gpd.read_file(project_dir / "study_area.geojson")
assert len(area) == 1 and area.geometry.is_valid.all()
assert area.crs is not None and area.crs.to_epsg() == 4326
polygon = area.geometry.iloc[0]
print("Study area CRS:", area.crs, flush=True)
print("Source:", source_url, flush=True)

# 2. Read a small native-resolution COG window. No full tile download.
if not raw_path.exists():
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT=60):
        with rasterio.open(source_url) as src:
            print("Source width / height:", src.width, src.height, flush=True)
            print("Source CRS / pixel size / NoData:", src.crs, src.res, src.nodata, flush=True)
            print("Source bounds:", src.bounds, flush=True)
            assert src.crs == area.crs, "Unexpected CRS; stop before clipping"
            assert src.nodata == 0 and src.dtypes[0] == "uint8"
            assert box(*src.bounds).covers(polygon), "Test area is outside this tile"
            win = from_bounds(*area.total_bounds, transform=src.transform)
            col0, row0 = max(0, math.floor(win.col_off) - 1), max(0, math.floor(win.row_off) - 1)
            col1 = min(src.width, math.ceil(win.col_off + win.width) + 1)
            row1 = min(src.height, math.ceil(win.row_off + win.height) + 1)
            window = Window(col0, row0, col1 - col0, row1 - row0)
            pixels = src.read(1, window=window)
            validity = src.read_masks(1, window=window)
            palette = src.colormap(1)  # Use the product's own colour table.
            profile = dict(
                driver="GTiff", height=pixels.shape[0], width=pixels.shape[1],
                count=1, dtype="uint8", crs=src.crs, nodata=0,
                transform=src.window_transform(window), compress="deflate",
            )
            record = {
                "product": "ESA WorldCover 10 m 2021 v200", "source_url": source_url,
                "documentation": "https://esa-worldcover.org/en/data-access",
                "doi": "https://doi.org/10.5281/zenodo.7254221",
                "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                "source_width": src.width, "source_height": src.height,
                "source_crs": str(src.crs), "source_resolution_degrees": list(src.res),
                "source_nodata": src.nodata, "source_bounds": list(src.bounds),
                "source_tags": src.tags(), "study_bbox": area.total_bounds.tolist(),
                "window_col_row_width_height": [col0, row0, col1 - col0, row1 - row0],
                "processing": "Native pixel window; no resampling, reprojection or class changes.",
                "classes": labels, "license": "CC BY 4.0", "attribution": attribution,
            }
            with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
                with rasterio.open(raw_path, "w", **profile) as dst:
                    dst.write(pixels, 1)
                    dst.write_mask(validity)
                    dst.write_colormap(1, palette)
                    dst.update_tags(**src.tags())
            source_record.write_text(json.dumps(record, indent=2), encoding="utf-8")
else:
    print("Reusing source window without modifying it.", flush=True)
    if not source_record.exists():
        raise RuntimeError("Source metadata is missing; inspect before continuing.")

# 3. Polygon mask: keep native class IDs; outside pixels use NoData=0.
with rasterio.open(raw_path) as src:
    assert src.crs == area.crs and src.nodata == 0
    assert box(*src.bounds).covers(polygon)
    palette = src.colormap(1)
    clipped, transform = mask(src, [mapping(polygon)], crop=True, filled=False)
    landcover = clipped[0]  # Shape: (rows, columns); each value is a class ID.
    inside = geometry_mask([mapping(polygon)], out_shape=landcover.shape,
                           transform=transform, invert=True)
    missing_inside = inside & np.ma.getmaskarray(landcover)
    assert landcover.count() > 0, "No valid land-cover pixels"
    values, counts = np.unique(landcover.compressed(), return_counts=True)
    unknown = set(values.tolist()) - set(labels)
    assert not unknown, f"Unexpected class IDs: {unknown}"
    profile = src.profile.copy()
    profile.update(height=landcover.shape[0], width=landcover.shape[1], transform=transform)
    with rasterio.open(clip_path, "w", **profile) as dst:
        dst.write(landcover.filled(0), 1)
        dst.write_colormap(1, palette)

# 4. Reopen the result; verify category values survived the save unchanged.
with rasterio.open(clip_path) as src:
    saved = src.read(1, masked=True)
    assert saved.shape == landcover.shape
    assert np.array_equal(np.ma.getmaskarray(saved), np.ma.getmaskarray(landcover))
    assert np.array_equal(saved.compressed(), landcover.compressed())
    print("\n--- WorldCover checks ---")
    print("Product year / version: 2021 / v200")
    print("Width / height:", src.width, src.height)
    print("Array shape (rows, columns):", saved.shape)
    print("Data type / CRS / NoData:", saved.dtype, src.crs, src.nodata)
    print("Pixel size (degrees):", src.res)
    print("Output bounds:", src.bounds)
    print("Class IDs:", values.tolist())
    print("Class counts and share of VALID pixels (not exact area shares):")
    for value, count in zip(values, counts):
        print(f"{value:3d} | {labels[int(value)]:25s} | {count:7d} | {100 * count / counts.sum():6.2f}%")
    print("Valid pixels:", saved.count())
    print("Missing pixels INSIDE boundary:", int(missing_inside.sum()), "/", int(inside.sum()))
    print("No resampling, reprojection or category merging performed.")
    west, south, east, north = array_bounds(src.height, src.width, src.transform)

# 5. Discrete colour lookup by original ID; no continuous colour interpolation.
colours = np.zeros((256, 4), dtype=float)
for value, rgba in palette.items():
    colours[value] = np.array(rgba) / 255
cmap = ListedColormap(colours)
cmap.set_bad("white")
fig, ax = plt.subplots(figsize=(10, 9))
ax.imshow(saved, extent=(west, east, south, north), origin="upper",
          cmap=cmap, norm=NoNorm(), interpolation="nearest")
area.boundary.plot(ax=ax, color="black", linewidth=0.9)
ax.set_title("Shenzhen test area - ESA WorldCover 2021 v200")
ax.set_xlabel("Longitude (degrees; WGS 84)")
ax.set_ylabel("Latitude (degrees; WGS 84)")
ax.ticklabel_format(useOffset=False, style="plain")
legend = [Patch(facecolor=colours[value], label=f"{value} - {labels[int(value)]}") for value in values]
ax.legend(handles=legend, loc="upper left", bbox_to_anchor=(1.01, 1), title="Classes present", fontsize=8)
fig.text(0.5, 0.015, attribution + "\nBlack: test boundary | White: masked pixels", ha="center", fontsize=7)
fig.tight_layout(rect=(0, 0.07, 1, 1))
map_path = maps_dir / "worldcover_test.png"
fig.savefig(map_path, dpi=200, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("Source window:", raw_path)
print("Clipped WorldCover:", clip_path)
print("Map:", map_path)
if missing_inside.any():
    raise RuntimeError("Missing pixels inside the boundary. Inspect before continuing.")
print("WorldCover technical checks passed. Inspect the PNG before continuing.")
