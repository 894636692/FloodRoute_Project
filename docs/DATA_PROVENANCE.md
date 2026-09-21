# Data provenance

| Category | Files / meaning |
|---|---|
| REAL | C government raw archives (local); normalized actual `shenzhen_grid/rainfall.csv` |
| DERIVED_FROM_REAL | A GPKG, grid registry with centres, edge/grid weights, real-input risk/routes |
| SIMULATED_SCENARIO | `data/scenarios/simulated_extreme/`, independent and temporal experiment results |
| OPTIONAL_EXTERNAL | IMERG importer only; no actual IMERG acquired or used |
| REAL_HISTORICAL_COARSE_FORCING | NASA POWER MERRA-2 hourly precipitation for 2023-09-07/08 external replay |
| REPORTED_EVENT_WEAK_LABEL | Official/public reports of impacted locations, used only for offline evaluation |
| SIMULATED_EXPANDED_VALIDATION | Three new rainfall families on the real 4,232-grid geometry, frozen parameters |

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

## Historical event validation

The 2023-09-07/08 replay uses NASA POWER Hourly API `PRECTOTCORR`, based on MERRA-2, explicitly requested in UTC. The original response is preserved at `data/historical/shenzhen_2023_0907/raw/nasa_power_prectotcorr_20230907_20230909_utc.json` with SHA256 `58bdd31e27c00b9ff2e16aeed4efe80440073833993a889b31faca990b9a522a`. Its meteorological grid is about 0.5° × 0.625°; the single point series is copied without interpolation to the model grid solely to exercise the frozen mapping pipeline. It is regional forcing, not Shenzhen station rain and not road-level truth.

Official Shenzhen sources supply event timing, aggregate rainfall facts, transport impacts and reported locations. `source_manifest.json` records URLs and supported facts. `impact_reports.csv` stores 10 weak-label records; only one road segment is both auditable and inside the formal network. Its coordinate is an explicitly recorded OSM road-object match, not a fabricated incident coordinate. Unreported roads are not confirmed negatives.

The official Shenzhen grid API requires an approved `appKey`, and GPM IMERG Final V07 requires Earthdata access. Neither authentication boundary was bypassed. Full provenance and suitability decisions are in `HISTORICAL_VALIDATION_SOURCE_AUDIT.md` and `HISTORICAL_EVENT_VALIDATION.md`.

## Expanded controlled validation

The three families `moving_center`, `dual_center` and `anisotropic_band` are simulated values over the real Shenzhen grid geometry. They are not historical observations. Scenario seeds `7101–7112`, OD selection seed `7201`, bootstrap seed `7301`, configuration hash and all perturbation levels were committed before results. `results/expanded_validation/protocol.json`, `scenario_manifest.csv` and `config_snapshot.json` preserve the exact evaluation provenance.
