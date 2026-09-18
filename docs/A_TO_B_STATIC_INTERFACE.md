# A -> B Static GIS Interface v1.0.0

`data/derived/static/road_static_features.gpkg` is the only A -> B static GIS input.
It contains the `road_static_features` layer in EPSG:32650. The `audit_20_edges` layer
is a deterministic 20-edge spatial review sample and is not a routing input.

## Stable contract

Every record is one directed OSM MultiDiGraph edge identified only by `(u, v, key)`.
`u` and `v` are original OSM node IDs. `key` distinguishes parallel directed edges.
Use `length_m` for the shortest-route baseline. All normalized fractions and risk-like
attributes are in `[0, 1]`. A missing measurement stays NULL and is accompanied by
`quality_flag`; zero never means unknown.

| Field | Type / unit | Contract |
| --- | --- | --- |
| `u`, `v`, `key` | int | immutable directed OSM edge ID |
| `geometry` | LineString, EPSG:32650 | edge geometry used for all length/statistics |
| `length_m` | float / m | equals projected geometry length |
| `highway`, `oneway`, `name` | string | preserved OSM metadata |
| `elev_mean_m`, `elev_min_m` | float / m | 10 m along-line samples from 30 m DEM |
| `low_elev_norm` | 0-1 | inverse mean elevation, study-area 2nd to 98th percentile |
| `slope_mean_deg`, `slope_p90_deg` | float / degrees | slope statistics from DEM |
| `flatness_risk` | 0-1 | `clip(1 - slope_mean_deg / 15, 0, 1)` |
| `builtup_frac` | 0-1 | WorldCover class 50 fraction |
| `vegetation_frac` | 0-1 | WorldCover classes 10,20,30,40,90,95,100 fraction |
| `water_frac` | 0-1 | WorldCover class 80 fraction |
| `dem_valid_frac`, `slope_valid_frac`, `worldcover_valid_frac` | 0-1 | valid samples divided by total samples |
| `quality_flag` | string | `ok` or semicolon-separated insufficiency flags |
| `source_version`, `schema_version` | string | reproducibility and compatibility identifiers |

## Rebuild and acceptance

Run from PowerShell:

```powershell
& "D:\LaotuZhBi\software\QGIS\bin\python-qgis-ltr.bat" `
  "D:\LaotuZhBi\laotu-data\scripts\build_road_static_features.py" `
  --root "D:\LaotuZhBi\laotu-data"
```

The build reads only `study_area.geojson`, raw OSM, raw DEM and raw WorldCover. It writes
30 m aligned rasters, `roads.graphml`, the GPKG, `manifest.json`, and `quality_report.json`.
The report checks CRS, required fields, duplicate `(u,v,key)`, graph/GPKG edge equality,
geometry-length equality, range validity, raster alignment, feature completeness and source hashes.

Open `a_to_b_interface_review.qgz` in QGIS to inspect the 20 red audit roads. The output is
a validation-area deliverable because `study_area.geojson` has `test_only: true`; update that
one file after the team freezes the final study area, then rebuild.

## B-side usage

B reads the GPKG rather than the legacy `roads_static_risk.geojson`. Build a directed
MultiDiGraph with the same `(u,v,key)` keys, use `length_m` for `shortest_cost`, and keep
static-risk weights in B configuration. A does not set a final static-risk formula.
