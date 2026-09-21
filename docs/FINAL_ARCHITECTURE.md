# Final v1 architecture

> 以下公式保留 v1 基线。v1.1 新界面使用 `config/selected_v1_1.json`，差异见文末；正式数据与风险组成未改变。

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

## v1.2 interaction, query and experiment boundary

`scripts/run_demo.py` → `ui/app_v1_1.py` → `ui/observations.py` → available observations → `Runtime.observed_state_with_sources` → `Runtime.plan`.
The app receives observation snapshots; the provider privately invokes scenario observation generation. Neither route planning nor the UI reads offline evaluation results.

`ui/components/leaflet_picker/` owns one persistent browser `L.Map`. Streamlit sends JSON state for markers, route, bounds, layer values and tile mode; it does not regenerate Folium HTML or change the component key. Static local roads, 4,232 grid polygons and 26,254 simplified risk-display road geometries are browser assets. Grid/risk reruns send compact `[feature_id,value,style_level]` arrays. Display geometry never enters routing or experiments.

`ui/controller.py` transforms WGS84 clicks to EPSG:32650 and finds the nearest formal candidate motor edge. The displayed marker uses the nearest point on the road, while `snapped_node_id` retains the closer routable endpoint. Endpoint selection accepts at most 100 m (`selectable_distance_m`) and keeps the 500 m backend safety threshold. Rejected clicks preserve endpoints, old results and viewport. “查看信息” bypasses this selection threshold, does not plan, and queries the nearest official grid plus formal road features/current risk through `ui/map_data.py`.

`Runtime.observed_state_with_sources` returns the unchanged `RiskEngine.compute` result together with its mapped observed rainfall frame for explanation. It does not change coefficients or the formal state. Only the source-supported preceding 1-hour accumulation is shown; no unsupported 3h/6h/24h totals are generated. Water remains inactive and no risk index is converted to depth.

Session state holds endpoints, query point, current observed snapshot, result and fit revision. Clear/swap/new points or scene/time/strategy/perturbation changes invalidate the previous result. Request IDs prevent a carried-over click from being consumed again when changing mode. Original `app.py` and its baseline remain; v1.2 regressions are separate.

Replay uses fixed user-selected endpoints and unchanged `ReplayController`: new observations → current route evaluation → trigger/cooldown → candidate search → minimum improvement → switch/keep. Initial planning is the only exception because there is no previous route. Metrics are recomputed under current observations even when retaining the old route. The result time is displayed separately from the single-run time selector.

Selected v1.1 parameters: rain tau 60 min, uncertainty weight .30, staleness weight .15, risk alpha 4, trusted alpha 5, risk-increase threshold .08, minimum improvement .03. Static/rain coefficients, uncertainty construction and inactive water/forecast remain unchanged. UI and v2 planning use `selected_v1_1.json`; original v1 experiment commands deliberately retain `final_v1.json`.

`experiments/v2.py` owns disjoint calibration/validation/test seeds and offline evaluation. Evaluation uses frozen base risk coefficients. Four methods receive paired observations at fixed OD/time cases. Selection is persisted and hashed before test data generation. Hashes normalize UTF-8 text to LF for Windows/Git reproducibility; timings do not enter selection artifacts or scoring.

`experiments/benchmarks.py` generates real-grid spatial rainfall fields centred on a dry baseline route midpoint. No target alternative edge IDs are encoded. T1/T2 latent data and offline metrics remain in the experiment directory. `scripts/run_trigger_benchmarks.py` replays frozen parameters without reselecting them. These are constructed software stress tests, not natural-event reconstructions.
