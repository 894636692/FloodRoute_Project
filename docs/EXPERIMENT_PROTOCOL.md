# Experiment protocol v1

## Scenario

Real A network/static attributes and C grid geometry; **generated** preceding-hour rainfall over 17
quarter-hour times, 2023-09-07 12:00–16:00 (+08:00), scenario_type=simulated_extreme.
Seed 20260920, smooth moving field, amplitude 120 mm, background 2 mm; all parameters retained.
These dates label a controlled scenario, not historical observations or a hydrodynamic simulation.

Observed is generated with delay, Bernoulli grid missingness and multiplicative Gaussian noise
(negative results clipped to zero). Only available fields cross into planner. Truth stays in generation
and offline evaluation. No truth-derived sensitivity/corridor is inserted; priors use A static features.

## Independent factorial experiment

- Delay: 0,15,30,60,120 min; missing: 0,.2,.4; multiplicative noise SD: 0,.1,.2.
- Baselines: shortest, risk, risk_uncertainty, trusted.
- Tau: source-specific versus universal 60 min. Only rain active, so effectively 45 versus 60 min.
- Decision time: middle of sequence, 14:00, with two hours of prehistory.
- OD: (114.030,22.535) → (114.090,22.570), snapped to candidate motor network.
- 45×4×2=360 independent decisions; no current_route shared across combinations.

Seeds depend on factor values, not run order. Methods share the same Observed in each combination;
factor/method orders are seeded permutations. Realized missing fraction may differ from target probability.
Truth evaluation uses contemporaneous latent scenario R, not trusted R.

`truth_exposure = sum(edge_length * truth_risk) / sum(edge_length)`.

Also report distance, max, length-weighted p95, length ratio with R≥.65 and computation_ms.
Timing includes mapping/state/search, excludes startup and offline evaluation; shared work is charged
consistently to each method. Wall-clock timing is not deterministic.

## Temporal replay

Independent never/always/triggered controllers advance the same increasing times with delay=30 min,
missing=.2, noise=.1. Each retains current_route, last_route_evaluation and last_replan_at.
Insufficient startup history means missing observations, never future filling.

Re-evaluate CURRENT route under the new state before checking confidence<.55, high-risk length ratio>.22,
or exposure increase>.08. Cooldown=30 min; hysteresis margin=.03. Only a positive trigger calls route search.
Switch only if candidate reduces current trusted total route cost by ≥3%. Rejected searches still count
as replan attempts and reset cooldown. Safe conditions rearm alarms; fresh risk increases can trigger independently.

Never searches initially only; always searches each time and accepts the optimum; triggered applies its
gate and minimum improvement. Counts exclude initial planning. Route changes compare exact edge sequences.
Mean replay exposure/distance averages per-time length-weighted metrics at equal intervals. It is a fixed
OD decision experiment, not vehicle movement or accumulated trip exposure.

## Reproduction and limits

```shell
python scripts/run_scenario_experiments.py
python scripts/run_trigger_replay.py
```

Both full results were repeated; `results/reproducibility.json` records equality excluding timing.
Tests also reverse combination order and change future truth to verify independence.
Earlier `smoke` results precede motor-road filtering and are not final evidence; use `independent.csv`.
One seed/OD is a demonstration, not independent empirical replication. No significance or universal
superiority claim. Multiple seeds, ODs and actual storm observations are needed for external validation.
