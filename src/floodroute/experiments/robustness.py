"""Independent paired factorial runs. No current route or replay state is shared."""
import copy
import itertools
import time
import numpy as np
import pandas as pd
from dataclasses import replace
from .scenario import observe
from floodroute.risk.dynamic import map_rainfall
from floodroute.risk.trusted import RiskEngine
from floodroute.runtime import route_metrics, write_json

BASELINES=('shortest','risk','risk_uncertainty','trusted')


def truth_metrics(route, truth_state, lengths, threshold):
    metrics=route_metrics(route,truth_state,lengths,threshold)
    return {'distance_m':metrics['distance_m'],'truth_exposure':metrics['risk_exposure'],
            'max_truth_risk':metrics['max_risk'],'p95_truth_risk':metrics['p95_risk'],
            'high_risk_length_ratio':metrics['high_risk_length_ratio']}


def run_independent(runtime, truth, request, combinations=None):
    cfg=runtime.config; ex=cfg['experiment']; base_seed=cfg['scenario']['random_seed']
    combos=list(combinations if combinations is not None else itertools.product(ex['delays_min'],ex['missing_rates'],ex['noise_levels']))
    # Evaluation is outside planning. Same latent scenario risk for every method.
    latent=observe(truth,request.timestamp,seed=base_seed)
    truth_state=runtime.observed_state(latent,request.timestamp)
    lengths=runtime.edges.set_index(['u','v','key']).length_m
    engine_specific=RiskEngine(runtime.edges,cfg)
    universal=copy.deepcopy(cfg)
    for settings in universal['sources'].values(): settings['tau_min']=ex['universal_tau_min']
    engine_universal=RiskEngine(runtime.edges,universal)
    order=np.random.default_rng(base_seed).permutation(len(combos))
    rows=[]
    for index in order:
        delay,missing,noise=combos[index]
        seed=base_seed+int(delay)*10000+round(missing*100)*100+round(noise*100)
        observed=observe(truth,request.timestamp,delay,missing,noise,seed)
        start=time.perf_counter()
        mapped=map_rainfall(observed,runtime.weights,runtime.coverage,request.timestamp)
        mapping_ms=(time.perf_counter()-start)*1000
        for tau,engine in [('source_specific',engine_specific),('universal',engine_universal)]:
            start=time.perf_counter();state=engine.compute({'rain':mapped});state_ms=(time.perf_counter()-start)*1000
            modes=np.random.default_rng(seed).permutation(BASELINES)
            for mode in modes:
                begin=time.perf_counter()
                route=runtime.plan(state,replace(request,mode=str(mode)))
                planning_ms=(time.perf_counter()-begin)*1000
                rows.append({'scenario_type':'simulated_extreme','delay_min':delay,'missing_rate':missing,'noise':noise,
                    'seed':seed,'tau_policy':tau,'mode':str(mode),**truth_metrics(route,truth_state,lengths,cfg['routing']['high_risk']),
                    'computation_ms':mapping_ms+state_ms+planning_ms,'planning_ms':planning_ms,
                    'edge_ids':';'.join(','.join(map(str,e)) for e in route.edge_ids)})
        print(f'Independent scenario {len(rows)//8}/{len(combos)} complete',flush=True)
    return pd.DataFrame(rows).sort_values(['delay_min','missing_rate','noise','tau_policy','mode']).reset_index(drop=True)
