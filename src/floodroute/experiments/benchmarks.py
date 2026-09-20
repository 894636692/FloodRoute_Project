"""Deterministic synthetic rain fields over real Shenzhen cells and motor roads.

The storm centre uses the dry baseline geometry to construct a challenge, not
to force an alternative route. No edge ID or desired answer is encoded.
"""
from dataclasses import replace
import numpy as np
import pandas as pd
from .scenario import observe
from .replay import ReplayController
from .robustness import truth_metrics


def benchmark_truth(grids, config, centre, name, seed=8801, width_m=700.):
    cells = grids.sort_values('grid_id').reset_index(drop=True)
    xy = cells.geometry.centroid
    radius2 = ((xy.x.to_numpy()-centre[0])**2 + (xy.y.to_numpy()-centre[1])**2)
    spatial = np.exp(-radius2/(2*width_m**2))
    factors = np.random.default_rng(seed).uniform(.98, 1.02, len(cells))
    amplitudes = ([0, 0, 10, 25, 50, 90, 140, 160, 160, 160, 160, 160]
                  if name == 'T1' else [8 + 2*np.sin(i*np.pi/2) for i in range(12)])
    rows = []
    for t, amplitude in zip(pd.date_range(config['scenario']['start'], periods=12, freq='15min'), amplitudes):
        rows.append(pd.DataFrame({'grid_id': cells.grid_id.astype(str), 'timestamp': t,
            'window_start': t-pd.Timedelta(hours=1), 'rain_mm': 1+amplitude*spatial*factors,
            'interval_min': 60, 'quality_flag': 'simulated_benchmark', 'scenario_type': name,
            'random_seed': seed}))
    return pd.concat(rows, ignore_index=True)


def benchmark_run(runtime, truth, request):
    """Offline evaluator owns truth; controllers receive only current observations."""
    import time
    controls = {policy: ReplayController(runtime, policy) for policy in ('never', 'always', 'triggered')}
    rows = []; initial_route = None
    for t in sorted(truth.timestamp.unique()):
        start = time.perf_counter()
        observed = observe(truth, t)
        state = runtime.observed_state(observed, t)
        mapping_ms = (time.perf_counter()-start)*1000
        evaluation = runtime.observed_state(observe(truth, t), t)
        for policy, control in controls.items():
            start = time.perf_counter()
            log = control.step(state, replace(request, timestamp=t.isoformat()))
            elapsed_ms = (time.perf_counter()-start)*1000
            if initial_route is None: initial_route = control.current_route
            metrics = truth_metrics(control.current_route, evaluation, control.lengths, runtime.config['routing']['high_risk'])
            original = truth_metrics(initial_route, evaluation, control.lengths, runtime.config['routing']['high_risk'])
            rows.append({**log, **metrics, 'initial_route_truth_exposure': original['truth_exposure'],
                         'computation_ms': mapping_ms+elapsed_ms,
                         'edge_ids': ';'.join(','.join(map(str, edge)) for edge in control.current_route.edge_ids)})
    return pd.DataFrame(rows)


def dry_centre(runtime, grids, request):
    dry = benchmark_truth(grids, runtime.config, (0, 0), 'T1')
    t = dry.timestamp.min()
    route = runtime.plan(runtime.observed_state(observe(dry, t), t), replace(request, timestamp=t.isoformat()))
    point = route.geometry.interpolate(.5, normalized=True)
    return [point.x, point.y]
