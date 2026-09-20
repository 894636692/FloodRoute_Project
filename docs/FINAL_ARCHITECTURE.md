# Final v1 architecture

```text
A GPKG → static susceptibility + missing-feature fraction
C grid corners → polygons 4326→32650 → cached edge/grid intersection weights
C Observed rainfall → latest available grid values → length-weighted edge rain
        → active-source risk/freshness/uncertainty → MultiDiGraph route → WGS84 UI

Scenario Truth → observation generator → Observed → planner
        └───────────────────────────────────────→ offline evaluation only
```

`gis/schema.py` isolates A constants from B's unchanged `common/schema.py`.
`gis/io.py` validates A layer/CRS/schema, IDs, geometry length, fractions and quality flags.
`gis/static_features.py` is the original A GDAL preprocessing pipeline; runtime never imports it.

`gis/grid_mapping.py` intersects true grid polygons with metric edge geometries. Mapping fields:
`u,v,key,grid_id,overlap_length_m,weight`. Covered weights sum to one; actual spatial coverage is separately
stored in `edge_coverage.parquet`. Union geometry avoids double-counting shared cell boundaries.
Hash manifests invalidate mappings after inputs change. No per-route nearest-grid search occurs.

`dynamic/grid_source.py` checks timezone, hourly accumulation window and uniqueness; duplicate grid/time
records require explicit resolution, not silent deletion. `risk/dynamic.py` selects only measurements
at/before decision time and excludes known later retrieval times. Unknown retrieval time is retained
under the declared real snapshot-replay limitation. Grid centres are not physical stations.

`RiskEngine.compute(observed_sources)` consumes per-source edge frames indexed by `(u,v,key)` with
`value,age_min,coverage,quality`. `Runtime.plan(state,request)` receives an observed risk frame and OD/time/mode.
Neither interface reads truth files. Generators and offline evaluators live under `experiments/`.

## Configured heuristic

All parameters: `config/final_v1.json`, copied to results. No fitted flood probabilities are claimed.

- S = .42 low elevation + .24 flatness + .22 built-up + .10 water fraction + .02 (1−vegetation).
- Features with corresponding raster validity <.9, nonfinite values, or insufficiency flags use
  explicit **0.5 prior**, and add to `static_missing_fraction`. Inputs remain unchanged.
- Rain risk = clip(mm/80); dynamic missing coverage uses declared .5 prior with uncertainty.
- R = weighted mean of static and **active** sources; default static/rain weights .45/.55.
- F_i = exp(−age_i/tau_i) × available coverage. Rain/water/forecast taus are 45/20/90 min;
  missing/future ages yield zero. Only rain is active by default.
- U = clip(.08 + .3 static_missing_fraction + mean_active(.5 missing_coverage + .15 quality)).
  Flags are semicolon tokens: bad/invalid/missing=1; qualified/unknown metadata=.5.
- C = mean_active(F_i) × (1−U). With no active sources, dynamic freshness is neutral (1).
- Risk+U = clip(R+.30U); trusted T = clip(R+.30U+.25(1−mean_active(F_i))).

Inactive water/forecast do not change weights, penalties or confidence. Missing active observations
are different from intentionally inactive sources. C/U are indices, not calibrated probabilities.

## Router

All A edges remain in storage and mapping. Runtime selects candidate motor roads via highway/access
tags; explicit restrictions and conditional access are excluded. Specific motor tags override general
access. Original direction and `(u,v,key)` are preserved. Relation-based turn restrictions are not modeled.

RoadNetworkRouter caches static data, endpoints and their spatial index. Its formal `plan_frame` uses
cost arrays on the same MultiDiGraph, without per-route graph copies. Parallel keys use actual mode cost.

Costs: shortest=L; risk=L(1+4R); risk+U=L(1+4 clip(R+.30U)); trusted=L(1+4.8T), using the clipped indices above.
Travel time=L/8 m/s is an estimate. Exposure/confidence/freshness/U/high-risk fraction are length weighted;
p95 is a length-weighted quantile. Max preserves edge extremes. Invalid/remote (>2 km) OD points,
identical snapped nodes or no directed path yield clear errors.
