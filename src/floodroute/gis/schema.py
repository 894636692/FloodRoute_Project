"""Frozen A -> B v1 interface. Missing observations remain NULL."""

SCHEMA_VERSION = "1.0.0"
COMPUTE_CRS = "EPSG:32650"
EDGE_ID = ("u", "v", "key")
INT_FIELDS = ("u", "v", "key", "osm_way_id", "segment_index", "sample_count")
FLOAT_FIELDS = (
    "length_m", "elev_mean_m", "elev_min_m", "low_elev_norm",
    "slope_mean_deg", "slope_p90_deg", "flatness_risk", "builtup_frac",
    "vegetation_frac", "water_frac", "dem_valid_frac", "slope_valid_frac",
    "worldcover_valid_frac",
)
TEXT_FIELDS = (
    "highway", "oneway", "name", "source_version", "schema_version",
    "quality_flag", "osm_tags_json",
)
NORMALIZED_FIELDS = (
    "low_elev_norm", "flatness_risk", "builtup_frac", "vegetation_frac",
    "water_frac", "dem_valid_frac", "slope_valid_frac", "worldcover_valid_frac",
)
REQUIRED_FIELDS = INT_FIELDS + FLOAT_FIELDS + TEXT_FIELDS
FEATURE_FIELDS = (
    "elev_mean_m", "elev_min_m", "low_elev_norm", "slope_mean_deg",
    "slope_p90_deg", "flatness_risk", "builtup_frac", "vegetation_frac", "water_frac",
)
