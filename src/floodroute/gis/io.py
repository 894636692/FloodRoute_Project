"""Read A's formal interface without QGIS/osgeo runtime dependencies."""
from pathlib import Path
import geopandas as gpd
import numpy as np
from .schema import REQUIRED_FIELDS, NORMALIZED_FIELDS, SCHEMA_VERSION


def read_static(path: str | Path) -> gpd.GeoDataFrame:
    edges = gpd.read_file(path, layer="road_static_features")
    missing = set(REQUIRED_FIELDS) - set(edges.columns)
    if missing or edges.crs.to_epsg() != 32650:
        raise ValueError(f"Invalid A interface: missing={missing}, CRS={edges.crs}")
    if edges.empty or edges.duplicated(["u", "v", "key"]).any():
        raise ValueError("Empty or duplicate edge IDs")
    if not edges.schema_version.eq(SCHEMA_VERSION).all():
        raise ValueError("Unsupported A schema version")
    if not edges.geom_type.eq("LineString").all() or not edges.is_valid.all():
        raise ValueError("Invalid edge geometry")
    if not (edges.length_m.gt(0).all() and np.allclose(edges.length_m, edges.length, atol=.01)):
        raise ValueError("Projected edge length mismatch")
    for col in NORMALIZED_FIELDS:
        valid = edges[col].dropna()
        if not valid.between(0, 1).all():
            raise ValueError(f"Invalid fraction: {col}")
    if edges.quality_flag.isna().any():
        raise ValueError("Missing static quality flags")
    return edges
