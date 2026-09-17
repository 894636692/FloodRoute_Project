"""Step 2: check installed packages and GIS drivers; no map data is used."""

import importlib
import sys

print("Python:", sys.version)
print("Executable:", sys.executable)
print("Isolated environment:", sys.prefix != sys.base_prefix)

packages = [
    "geopandas", "rasterio", "shapely", "pyproj",
    "osmnx", "networkx", "numpy", "matplotlib",
]
for name in packages:
    module = importlib.import_module(name)
    print(f"[OK] {name}: {module.__version__}")

import rasterio
import pyogrio
from pyproj import CRS

# Look up a CRS definition only. No coordinates are transformed.
print("CRS database:", CRS.from_epsg(4326).name)
with rasterio.Env() as environment:
    assert "GTiff" in environment.drivers(), "GeoTIFF driver is missing"
    print("[OK] GeoTIFF driver; GDAL:", rasterio.__gdal_version__)
assert "GeoJSON" in pyogrio.list_drivers(), "GeoJSON driver is missing"
print("[OK] GeoJSON driver")
print("Environment checks passed.")
