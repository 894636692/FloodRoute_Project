# Limitations and remaining work

1. **Index, not depth.** Weights are transparent uncalibrated policies, not validated flood probabilities.
   Confidence and uncertainty are indices. No road inundation measurements or hydrodynamic model validate R.
2. **Static resolution.** Copernicus is DSM, not bare earth; A uses 30 m rasters and 10 m line samples.
   Drains, kerbs and underpasses are unresolved. WorldCover is from 2021. Unknown features use explicit
   0.5 priors and uncertainty; they are not silently dry/safe.
3. **Dry real sample.** One short export has zero hourly rainfall. Ten-minute timestamps represent
   overlapping preceding-hour accumulations; summing them as separate increments is invalid.
4. **Time evidence.** Rain time semantics are user-confirmed, retrieval time unknown. The real pipeline
   proves ingestion, not historical real-time availability. Controlled experiments model availability explicitly.
5. **Real water disabled.** Public coordinates, observation-time meaning and measurement datum are incomplete.
   Station/river water level is never equated with road flood depth.
6. **No validated ensemble.** Forecast source is inactive; no invented members or measured ensemble uncertainty.
7. **Candidate motor routes.** A includes footways/steps/construction; runtime filters to 55,727 motor candidates
   and checks explicit access. Missing tags, turn-restriction relations, barriers, vehicle dimensions,
   temporary closures and emergency permissions remain unmodeled. This is not operational navigation.
8. **Travel/time performance.** 8 m/s is a fixed estimate. Timing excludes startup and depends on hardware.
9. **Controlled experiments remain simulated.** The expanded test uses three spatial families, 12 seeds and
   eight OD pairs, but it still cannot cover all Shenzhen storms, drainage failures or traffic conditions.
   Trusted and risk+uncertainty were not consistently better than risk; Trigger missed a useful replan under
   the preregistered rule in 7 of 36 stress events.
10. **Historical validation is sparse and coarse.** NASA POWER MERRA-2 forcing is about 0.5° × 0.625° and
    severely smooths the documented local extreme. Only one reported road segment was both auditable and
    inside the formal network; it ranked at the 38.86th risk percentile and was outside the top 20%.
    This is a retained failure case, not evidence of historical prediction accuracy. IMERG remained blocked
    by Earthdata authorization and the Shenzhen official API required an approved appKey.
11. **A rebuild prerequisites.** Raw inputs remain on A's original branch with hashes. GPKG retrieved and
    validated; raw GDAL pipeline was not rerun locally. Runtime does not need QGIS; cloning needs LFS.
12. **Visual review scope.** Core interaction passed real-user Google Chrome review with zero console errors.
    Specific untested display resolutions, hardware combinations, extra browser versions and the full replay
    sequence remain pending and are not claimed as separate acceptance samples.

No external account is required for core v1. Missing official historical access and IMERG credentials
do not block the implemented demo or controlled experiments.

The evidence supports engineering reproducibility and limited findings within the controlled protocol. It
does not establish road inundation depth, calibrated safety probability, citywide historical recall, or
readiness for operational emergency navigation.
