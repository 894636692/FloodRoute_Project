# Final v1 integration status

Branch: `integration/final-v1`, created from `feature/dynamic` (`d1721cd`).
Main remains `8ea17cd`; A source is `origin/team-a-static-interface-2026-09-18` (`aaaf328`).
A has separate history: selectively import files, never merge the branch.

## Phase log

| Phase | State | Validation |
|---|---|---|
| 0 | Complete | Fresh fetch; tracked working tree clean; 35 unittest tests pass |
| 1–13 | Pending | Execute sequentially and commit separately |

## Data and blockers

- REAL: Shenzhen hourly grid rainfall and grid registry; observed rainfall currently zero.
- DERIVED_FROM_REAL: A formal OSM/DEM/WorldCover features (LFS retrieval pending).
- SIMULATED_SCENARIO: not yet built; root dynamic CSVs are legacy fixtures.
- OPTIONAL_EXTERNAL: historical regional forcing; no external credentials available.
- Shenzhen water is inactive: public spatial coordinates, time semantics and datum unverified.
- Existing local untracked raw/interim files, reports and work files preserved.
- Baseline runner is `python -m unittest discover -s tests -v`; pytest is not installed or required.

Output is a road flood risk index, not a prediction of physical flood depth.

Phase 1 complete: official A LFS SHA256 verified; 112218 directed edges, 46468 nodes; 36 tests passed. B fixture preserved in tests/fixtures; A schema isolated. Formal data provenance manifest retained. QGIS/osgeo only required to rebuild from original A raw inputs, not to run.

Phase 2 complete: 26 C tests + 2 formal source tests passed. Grid rainfall accepted with user-confirmed time semantics retained in quality flags; missing retrieval time remains unknown. Water and forecast disabled in config/final_v1.json.

Phase 3 complete: all 112218 edges mapped, 121153 intersection records; road-length coverage 99.9999999984%. Retain A study area. Mapping tests (2) pass, input hashes persisted. Parquet runtime dependency added.

Phase 4 complete: formal vectorized risk/static/dynamic/freshness/trusted modules; 4 focused tests pass. Missing values use declared 0.5 prior with explicit uncertainty; only active sources contribute. Legacy B APIs retained for regression until archive cleanup.

Phase 5 complete: real A+C pipeline produced shortest/risk/trusted GeoJSON and provenance; acceptance test passed. Route lengths 10447/10491/10491 m, real rain remains zero. Metrics are length weighted; confidence is an index, not calibrated probability.
