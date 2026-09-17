"""Step 7: geographic overlay only; no downloads or input-data changes."""

import json
import os
from pathlib import Path

project_dir = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(project_dir / "work" / "matplotlib"))

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, NoNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.plot import plotting_extent
from shapely.geometry import box, mapping

area = gpd.read_file(project_dir / "study_area.geojson")
roads = gpd.read_file(project_dir / "data/processed/osm/roads.geojson")
maps_dir = project_dir / "outputs/maps"
maps_dir.mkdir(parents=True, exist_ok=True)
assert len(area) == 1 and area.geometry.is_valid.all()
assert area.crs is not None and area.crs.to_epsg() == 4326
assert roads.crs == area.crs and not roads.empty
assert roads.geometry.is_valid.all() and not roads.geometry.is_empty.any()
polygon = area.geometry.iloc[0]
# Tiny angular tolerance is for floating-point comparison, not a ground buffer.
assert roads.geometry.covered_by(polygon.buffer(1e-9)).all()

print("--- Overlay checks ---")
print("Shared display CRS:", area.crs)
print("Clipped road features:", len(roads))
layers = {}
report = {"display_crs": str(area.crs), "study_bbox": area.total_bounds.tolist(),
          "road_features": len(roads), "rasters": {},
          "reprojection": False, "resampling": False,
          "visual_alignment_review": "Pending human inspection of overlay maps"}

# Each array keeps its OWN transform, shape and geographic extent.
for name, path in [
    ("DEM", project_dir / "data/processed/dem/dem_clip.tif"),
    ("WorldCover", project_dir / "data/processed/worldcover/worldcover_clip.tif"),
]:
    with rasterio.open(path) as src:
        assert src.crs == area.crs, f"{name}: CRS mismatch; stop before plotting"
        assert box(*src.bounds).covers(polygon), f"{name}: incomplete spatial extent"
        # imshow extent below assumes a north-up grid, as these source files use.
        assert src.transform.b == 0 and src.transform.d == 0
        assert src.transform.a > 0 and src.transform.e < 0
        array = np.ma.masked_invalid(src.read(1, masked=True))
        inside = geometry_mask([mapping(polygon)], out_shape=array.shape,
                               transform=src.transform, invert=True)
        missing = int((inside & np.ma.getmaskarray(array)).sum())
        assert inside.any() and missing == 0, f"{name}: missing interior pixels"
        assert not ((~inside) & (~np.ma.getmaskarray(array))).any(), f"{name}: unexpected data outside shared boundary"
        layers[name] = {"array": array, "extent": plotting_extent(src)}
        if name == "WorldCover":
            palette = src.colormap(1)
        report["rasters"][name] = {
            "crs": str(src.crs), "shape": list(array.shape),
            "pixel_size_degrees": list(src.res), "bounds": list(src.bounds),
            "valid_pixels": int(array.count()), "missing_inside": missing,
        }
        print(f"{name}: CRS={src.crs}, shape={array.shape}, valid={array.count()}, missing_inside={missing}")
        print(f"{name} imshow extent [west, east, south, north]: {plotting_extent(src)}")

labels = {10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland",
          50: "Built-up", 60: "Bare / sparse vegetation", 70: "Snow and ice",
          80: "Permanent water bodies", 90: "Herbaceous wetland",
          95: "Mangroves", 100: "Moss and lichen"}
classes = np.unique(layers["WorldCover"]["array"].compressed())
assert set(classes.tolist()) <= set(labels)
colours = np.zeros((256, 4), dtype=float)
for value, rgba in palette.items():
    colours[value] = np.array(rgba) / 255
landcover_cmap = ListedColormap(colours)
landcover_cmap.set_bad((0, 0, 0, 0))
west, south, east, north = area.total_bounds

# Three views make it possible to inspect layers without opacity hiding errors.
views = [
    ("dem_osm_overlay.png", "DEM + OSM roads", True, False),
    ("worldcover_osm_overlay.png", "WorldCover 2021 + OSM roads", False, True),
    ("three_layers_overlay.png", "DEM + WorldCover 2021 + OSM roads", True, True),
]
for filename, title, show_dem, show_cover in views:
    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_axes([0.08, 0.14, 0.65, 0.77])
    if show_dem:
        dem_cmap = plt.get_cmap("gray" if show_cover else "viridis").copy()
        dem_cmap.set_bad((0, 0, 0, 0))
        dem_image = ax.imshow(
            layers["DEM"]["array"], extent=layers["DEM"]["extent"],
            origin="upper", cmap=dem_cmap, interpolation="nearest", zorder=1,
        )
    if show_cover:
        ax.imshow(
            layers["WorldCover"]["array"], extent=layers["WorldCover"]["extent"],
            origin="upper", cmap=landcover_cmap, norm=NoNorm(),
            alpha=0.50 if show_dem else 1.0, interpolation="nearest", zorder=2,
        )
    # White casing keeps the dark road lines visible over either background.
    roads.plot(ax=ax, color="white", linewidth=1.05, zorder=3)
    roads.plot(ax=ax, color="#20252b", linewidth=0.40, zorder=4)
    area.boundary.plot(ax=ax, color="black", linewidth=1.0, linestyle="--", zorder=5)
    ax.set_xlim(west - 0.0003, east + 0.0003)
    ax.set_ylim(south - 0.0003, north + 0.0003)
    ax.set_aspect(1 / np.cos(np.deg2rad((south + north) / 2)))
    ax.set_title(title, fontsize=13)
    ax.set_xlabel("Longitude (degrees; WGS 84)")
    ax.set_ylabel("Latitude (degrees; WGS 84)")
    ax.ticklabel_format(useOffset=False, style="plain")
    handles = [Line2D([0], [0], color="#20252b", label="OSM driving roads"),
               Line2D([0], [0], color="black", linestyle="--", label="Test boundary")]
    if show_cover:
        handles += [Patch(facecolor=colours[c], label=f"{c} - {labels[int(c)]}") for c in classes]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.75, 0.89),
               fontsize=8, title="Layers / source class colours")
    if show_dem:
        cax = fig.add_axes([0.79, 0.20, 0.018, 0.25])
        fig.colorbar(dem_image, cax=cax, label="DSM surface elevation (m; EGM2008)")
    if show_dem and show_cover:
        fig.text(0.76, 0.49, "WorldCover opacity: 50%\nColours blend with DEM.\nUse separate maps for\nunambiguous layer reading.", fontsize=8)
    fig.text(0.08, 0.07, "Sources: OpenStreetMap contributors (ODbL); Copernicus GLO-30 via AWS (DLR / Airbus, EU / ESA).", fontsize=7)
    fig.text(0.08, 0.05, "ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium.", fontsize=7)
    fig.text(0.08, 0.03, "Display overlay only: native raster grids preserved; no reprojection, resampling or positional shifts.", fontsize=8)
    output = maps_dir / filename
    fig.savefig(output, dpi=200, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print("Map saved:", output)

report["maps"] = [name for name, _, _, _ in views]
report_path = project_dir / "outputs/overlay_checks.json"
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print("Technical report:", report_path)
print("Overlay technical checks passed. Visual alignment review is still required.")
