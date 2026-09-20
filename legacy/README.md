# Archived prototypes

These files preserve early concept demonstrations and B's fixture entry points.
They are **not formal v1 experiment commands**. In particular, the old trigger
experiment compares delay settings at one time and is not a temporal replay.

The old MVP can be checked with `python -m legacy.main`; output stays in
`legacy/results/`. Its synthetic susceptibility/truth assumptions are preserved
for regression only and are not evidence for the final system.

`prepare_b_static_fixture.py` now targets `tests/fixtures/b_static.gpkg`; it can
never overwrite A's formal GPKG by default. Original B fixtures and compatibility
modules (`risk/models.py`, `routing/service.py`, `routing/trigger.py`, and
`experiments/trigger_experiment.py`) remain for old regression tests, not for v1.

Formal commands are exclusively:

```shell
python scripts/run_real_pipeline.py
python scripts/run_scenario_experiments.py
python scripts/run_trigger_replay.py
python scripts/run_demo.py
```
