"""Step 3: save one shared test boundary; no datasets are downloaded."""

from pathlib import Path

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import box

project_dir = Path(__file__).resolve().parents[1]
output_path = project_dir / "study_area.geojson"

# Candidate centre near Futian, Shenzhen; this is NOT the final study area.
center_lon = 114.055
center_lat = 22.545
side_m = 5000
geographic_crs = "EPSG:4326"
metric_crs = "EPSG:32650"  # WGS 84 / UTM zone 50N; units: metres.

# 1. Longitude/latitude (degrees) -> projected x/y (metres).
print(f"Centre conversion: {geographic_crs} -> {metric_crs}")
to_meters = Transformer.from_crs(geographic_crs, metric_crs, always_xy=True)
x, y = to_meters.transform(center_lon, center_lat)

# 2. Extend 2500 metres in each direction to create a 5000 x 5000 m square.
half = side_m / 2
square = box(x - half, y - half, x + half, y + half)
area_m = gpd.GeoDataFrame(
    {"name": ["Shenzhen_Futian_test"], "test_only": [True],
     "center_lon": [center_lon], "center_lat": [center_lat],
     "side_m": [side_m], "construction_crs": [metric_crs]},
    geometry=[square], crs=metric_crs,
)
print(f"Projected area: {area_m.geometry.area.iloc[0] / 1_000_000:.3f} km2")

# Add vertices along edges to preserve the boundary during reprojection.
area_m.geometry = area_m.geometry.segmentize(250)

# 3. Projected boundary (metres) -> WGS 84 longitude/latitude for GeoJSON.
print(f"Boundary conversion: {metric_crs} -> {geographic_crs}")
area = area_m.to_crs(geographic_crs)
min_lon, min_lat, max_lon, max_lat = area.total_bounds
for name, value in zip(
    ["min_lon", "min_lat", "max_lon", "max_lat"], area.total_bounds
):
    area[name] = float(value)
    print(f"{name}: {value:.8f}")

# The polygon is the shared clipping boundary. Its bbox is a download envelope.
if output_path.exists():
    raise FileExistsError(f"Boundary already exists; not overwritten: {output_path}")
area.to_file(output_path, driver="GeoJSON", index=False)
saved = gpd.read_file(output_path)
assert len(saved) == 1 and saved.geometry.is_valid.all()
assert saved.crs.to_epsg() == 4326
print("Saved features:", len(saved))
print("Saved CRS:", saved.crs)
print("Saved boundary:", output_path)
print("Study area checks passed.")
