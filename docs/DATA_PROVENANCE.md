# Data provenance

| Category | Files / meaning |
|---|---|
| REAL | C government raw archives (local); normalized actual `shenzhen_grid/rainfall.csv` |
| DERIVED_FROM_REAL | A GPKG, grid registry with centres, edge/grid weights, real-input risk/routes |
| SIMULATED_SCENARIO | `data/scenarios/simulated_extreme/`, independent and temporal experiment results |
| OPTIONAL_EXTERNAL | IMERG importer only; no actual IMERG acquired or used |

## A

Selectively imported from `aaaf328ab073d95fec71c8cf0c043408151b08cb`.
GPKG SHA256 `768982eb7ca617e0845082d4b6d846ae7e284d9128f82952c9db8a8bb6600aec`.
112,218 directed edges, 46,468 nodes, EPSG:32650, schema 1.0.0, complete-feature fraction .9911065961.
`data/derived/static/manifest.json` preserves OSM/Copernicus/WorldCover source hashes, versions and alignment;
`quality_report.json` preserves A checks. The retained study area is an integration/demo domain.

Runtime reproduction needs the formal GPKG LFS object and committed C/mapping files, not QGIS.
Full preprocessing reconstruction additionally needs A's original raw files listed in the manifest,
available on its original branch. Preserve relative paths and verify hashes. With GDAL Python:

```shell
python scripts/build_road_static_features.py
python scripts/build_grid_mapping.py
```

Not all A raw inputs exist in this checkout; preprocessing was imported and independently validated,
not rerun. Runtime input hashes are recorded in `results/real_pipeline/data_provenance.json`.

## C

[Official observations](https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_00903509),
[official grid registry](https://opendata.sz.gov.cn/data/dataSet/toDataDetails/29200_00903510).

100,000 records, 4,232 grids, 24 times from 2026-09-17T20:50:00+08:00 to 2026-09-18T00:40:00+08:00.
First snapshot has 2,664 grids; remaining 23 have 4,232. Preceding-hour rain is all zero.
GRIDID joins registry RECID. SZ_GRID compatibility IDs are not physical monitoring stations.
WGS84 grid corner CRS is supported by official metadata supplied in screenshots.

The user confirmed Beijing time and accumulation ending at FORECASTTIME. This evidence is user confirmation,
not independent agency verification. Download time is unknown; `retrieved_at` stays blank with quality flag.
Therefore real snapshots cannot prove what was available online at historical decision time.

Raw observation hash: `21f6ae170a34b8c4c2e5e8ac018209fbd988969dd913186f5fdbf104bd4c6d71`.
Raw registry hash: `6d53455a9c65757e553e34a3937a02a1e680d0a642405c41b697f0d6f79eae16`.
Raw/intermediate files stay local/ignored, unchanged. Normalized interfaces are committed.

真实水位没有合法公开空间坐标，因此未作为道路级真实动态输入。
时间语义/时区和测量基准也未完整核验，water.active=false。485 条名录及 148 站水位样本保留。
Root `data/derived/dynamic/rainfall.csv` and `water_level.csv` are legacy fixtures, not formal inputs.
Forecast ensembles inactive; no fabricated members. NOAA/ERA5 exploratory files are unused.

IMERG is OPTIONAL_EXTERNAL regional temporal forcing only. The 2023-09-07/08 event is a historical
reference, never the provenance of generated rainfall; see `HISTORICAL_EVENT_REFERENCE.md`.
