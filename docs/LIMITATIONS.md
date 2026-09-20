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
9. **Limited experiments.** Smooth synthetic rain is not a reconstructed historical storm. One seed/OD,
   simple noise and missingness; trusted is not guaranteed safer or shorter.
10. **IMERG unavailable.** No actual sample/credentials; importer tested only on synthetic accumulation TIFF.
    HDF/NetCDF not supported. Coarse regional forcing cannot establish street-level truth.
11. **A rebuild prerequisites.** Raw inputs remain on A's original branch with hashes. GPKG retrieved and
    validated; raw GDAL pipeline was not rerun locally. Runtime does not need QGIS; cloning needs LFS.
12. **Visual review pending.** Streamlit AppTest and live HTTP health passed. Browser connector failed
    (`nodeRepl.fetch request failed`), so no browser screenshot or visual acceptance is claimed. Target-screen
    review should check map rendering, alignment, Chinese layout and controls.

No external account is required for core v1. Missing official historical access and IMERG credentials
do not block the implemented demo or controlled experiments.
