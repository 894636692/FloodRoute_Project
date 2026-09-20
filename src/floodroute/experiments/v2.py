"""Separated parameter selection and held-out experiments with frozen evaluation.

Only this offline module sees latent truth. The router sees RiskEngine output
constructed from observe(...), and selection never receives the held-out seeds.
"""
import copy
import hashlib
import itertools
import json
import time
from dataclasses import replace
import numpy as np
import pandas as pd
from floodroute.runtime import ROOT, load_config, write_json
from floodroute.common.schema import RouteRequest
from floodroute.risk.trusted import RiskEngine
from floodroute.risk.dynamic import map_rainfall
from .scenario import generate_truth, observe
from .robustness import BASELINES, truth_metrics
from .benchmarks import benchmark_truth, benchmark_run, dry_centre


def selection_digest(path):
    """Git-normalized UTF-8/LF hash, identical on Windows and fresh checkouts."""
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def validate_split(split):
    groups = [set(split[key]) for key in ('calibration', 'validation', 'test')]
    if any(not values for values in groups) or any(a & b for a,b in itertools.combinations(groups, 2)):
        raise ValueError('Seed groups must be nonempty and disjoint')
    if any(len(split[k]) != len(set(split[k])) for k in split):
        raise ValueError('Duplicate seed in partition')


def profile_config(base, params, ablation='source_specific'):
    cfg = copy.deepcopy(base)
    cfg['sources']['rain']['tau_min'] = params['rain_tau']
    cfg['trusted'].update(staleness_weight=params['freshness_weight'], uncertainty_weight=params['uncertainty_weight'])
    cfg['routing'].update(risk_alpha=params['risk_alpha'], trusted_alpha=params['trusted_alpha'])
    cfg['trigger'].update(risk_increase=params['trigger_threshold'], minimum_improvement=params['minimum_improvement'])
    if ablation == 'no_freshness': cfg['trusted']['staleness_weight'] = 0.
    if ablation == 'universal':
        for source in cfg['sources'].values(): source['tau_min'] = 60
    return cfg


def configured(runtime, cfg):
    result = copy.copy(runtime)
    result.config = cfg
    result.engine = RiskEngine(result.edges, cfg)
    return result


def evaluate(runtime, grids, design, params, seeds, conditions, ablations, modes=BASELINES):
    base = load_config()
    lengths = runtime.edges.set_index(['u', 'v', 'key']).length_m
    evaluator = RiskEngine(runtime.edges, base)
    engines = {a: RiskEngine(runtime.edges, profile_config(base, params, a)) for a in ablations}
    cfg = profile_config(base, params)
    planning = configured(runtime, cfg)
    rows = []
    for seed in seeds:
        generation = copy.deepcopy(base); generation['scenario']['random_seed'] = seed
        latent = generate_truth(grids, generation)
        times = sorted(latent.timestamp.unique())
        for step in design['decision_steps']:
            at = times[step]
            # Evaluation risk has fixed coefficients across every profile/method.
            perfect = map_rainfall(observe(latent, at), runtime.weights, runtime.coverage, at)
            truth_state = evaluator.compute({'rain': perfect})
            order = np.random.default_rng(seed+step).permutation(len(conditions))
            for i in order:
                delay, missing, noise = conditions[i]
                observation_seed = seed + step*100000 + int(delay)*1000 + round(missing*100)*10 + round(noise*100)
                observed = observe(latent, at, delay, missing, noise, observation_seed)
                begin = time.perf_counter()
                mapped = map_rainfall(observed, runtime.weights, runtime.coverage, at)
                mapping_ms = (time.perf_counter()-begin)*1000
                for ablation in np.random.default_rng(observation_seed).permutation(ablations):
                    begin = time.perf_counter(); state = engines[ablation].compute({'rain': mapped})
                    state_ms = (time.perf_counter()-begin)*1000
                    for od_index, od in enumerate(design['ods']):
                        for mode in np.random.default_rng(observation_seed+od_index).permutation(modes):
                            request = RouteRequest(*od, at.isoformat(), str(mode))
                            begin = time.perf_counter(); route = planning.plan(state, request)
                            elapsed_ms = (time.perf_counter()-begin)*1000
                            rows.append(dict(seed=seed, od=od_index, decision_step=step, timestamp=at.isoformat(),
                                delay_min=delay, missing_rate=missing, noise=noise, ablation=str(ablation), mode=str(mode),
                                **truth_metrics(route, truth_state, lengths, base['routing']['high_risk']),
                                computation_ms=mapping_ms+state_ms+elapsed_ms,
                                route_id=route.route_id))
        print(f'Finished seed {seed}: {len(rows)} paired route evaluations', flush=True)
    return pd.DataFrame(rows)


def benchmark_summary(rows):
    return rows.groupby('policy').agg(mean_truth_exposure=('truth_exposure','mean'),
        replans=('replan_count','max'), switches=('route_change_count','max'),
        planner_calls=('planner_calls','max'), total_ms=('computation_ms','sum')).reset_index()


def score_profile(runtime, grids, design, params, seeds, centre):
    observations = evaluate(runtime, grids, design, params, seeds, design['calibration_conditions'],
                            ['source_specific'], modes=('shortest', 'trusted'))
    keys = ['seed','od','decision_step','delay_min','missing_rate','noise']
    shortest = observations[observations['mode'].eq('shortest')].set_index(keys).distance_m
    trusted = observations[observations['mode'].eq('trusted')].set_index(keys)
    route_score = float((trusted.truth_exposure + .1*trusted.distance_m/shortest).mean())
    r = configured(runtime, profile_config(load_config(), params))
    request = RouteRequest(*design['ods'][0], r.config['scenario']['start'], 'trusted')
    summaries = []; eligible = True
    for seed in seeds:
        for name in ('T1', 'T2'):
            truth = benchmark_truth(grids, r.config, centre, name, seed, design['benchmark_width_m'])
            table = benchmark_run(r, truth, request)
            summary = benchmark_summary(table).set_index('policy')
            triggered = summary.loc['triggered']; always = summary.loc['always']; never = summary.loc['never']
            safe_switch = triggered.switches >= 1 and triggered.mean_truth_exposure < never.mean_truth_exposure
            eligible &= bool(safe_switch if name == 'T1' else triggered.replans < always.replans)
            summaries.append(dict(seed=seed, benchmark=name, **triggered.drop('total_ms').to_dict()))
    frame = pd.DataFrame(summaries)
    score = route_score + .05*frame.mean_truth_exposure.mean() + .002*frame.replans.mean()
    return {'score': float(score), 'route_score': route_score, 'eligible': eligible,
            'benchmarks': summaries, 'route_evaluations': len(observations)}, observations


def run_v2(runtime, grids, directory):
    directory.mkdir(parents=True, exist_ok=True)
    design = json.loads((ROOT/'config/experiment_v2.json').read_text(encoding='utf-8'))
    validate_split(design['split'])
    write_json(directory/'scenario_split.json', design['split'])
    request = RouteRequest(*design['ods'][0], runtime.config['scenario']['start'], 'trusted')
    centre = dry_centre(runtime, grids, request)
    # Archive the declared design and development scenario BEFORE any selection.
    write_json(directory/'protocol.json', {**design, 'benchmark_centre_utm': centre,
        'evaluation_risk_config': load_config(), 'test_generation_started': False})
    calibration = {}; validation = {}
    for name, params in design['candidates'].items():
        calibration[name], records = score_profile(runtime, grids, design, params, design['split']['calibration'], centre)
        records.to_csv(directory/f'calibration_{name}.csv', index=False)
        print('Calibration', name, calibration[name]['score'], calibration[name]['eligible'], flush=True)
    candidates = sorted((name for name in calibration if calibration[name]['eligible']), key=lambda name: calibration[name]['score'])[:2]
    if not candidates: raise ValueError('No profile passes calibration safety benchmarks')
    for name in candidates:
        validation[name], records = score_profile(runtime, grids, design, design['candidates'][name], design['split']['validation'], centre)
        records.to_csv(directory/f'validation_{name}.csv', index=False)
        print('Validation', name, validation[name]['score'], validation[name]['eligible'], flush=True)
    eligible = [name for name in validation if validation[name]['eligible']]
    if not eligible: raise ValueError('No profile passes validation safety benchmarks')
    chosen = min(eligible, key=lambda name: validation[name]['score'])
    params = design['candidates'][chosen]
    selection = {'candidate_profiles': design['candidates'], 'candidate_ranges': {
        key: sorted({p[key] for p in design['candidates'].values()}) for key in params},
        'calibration_results': calibration, 'validation_results': validation,
        'selected_profile': chosen, 'final_parameters': params, 'selection_rule': design['selection_rule'],
        'objective': design['objective'], 'test_used_for_selection': False}
    write_json(directory/'parameter_selection.json', selection)
    selection_hash = selection_digest(directory/'parameter_selection.json')
    selected_config = profile_config(load_config(), params)
    write_json(ROOT/'config/selected_v1_1.json', selected_config)
    # This is the FIRST use of test seeds to generate data or evaluate any method.
    conditions = list(itertools.product(design['test_delays_min'], design['test_missing_rates'], design['test_noise']))
    heldout = evaluate(runtime, grids, design, params, design['split']['test'], conditions,
                       ['no_freshness','universal','source_specific'])
    heldout.to_csv(directory/'test_routes.csv', index=False)
    heldout.groupby(['ablation','mode'])[['distance_m','truth_exposure','max_truth_risk',
        'p95_truth_risk','high_risk_length_ratio','computation_ms']].mean().to_csv(directory/'test_summary.csv')
    selected = configured(runtime, selected_config)
    summaries = []
    for seed in design['split']['test']:
        for name in ('T1','T2'):
            truth = benchmark_truth(grids, selected_config, centre, name, seed, design['benchmark_width_m'])
            truth.to_parquet(directory/f'{name}_{seed}_truth.parquet', index=False)
            rows = benchmark_run(selected, truth, request)
            rows.to_csv(directory/f'{name}_{seed}_replay.csv', index=False)
            summary = benchmark_summary(rows); summary['benchmark'] = name; summary['seed'] = seed
            summaries.append(summary)
    pd.concat(summaries, ignore_index=True).to_csv(directory/'benchmark_summary.csv', index=False)
    if selection_digest(directory/'parameter_selection.json') != selection_hash:
        raise ValueError('Selection changed during test evaluation')
    write_json(directory/'run_manifest.json', {'selected_profile': chosen, 'selection_sha256_before_test': selection_hash,
        'selection_sha256_after_test': selection_hash, 'test_rows': len(heldout), 'test_seeds': design['split']['test'],
        'benchmark_centre_utm': centre, 'benchmark_width_m': design['benchmark_width_m'],
        'hash_format': 'UTF-8 with LF line endings',
        'complete': True, 'ground_truth_use': 'generation and offline evaluation only'})
