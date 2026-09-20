"""Chronological replay: evaluate current route BEFORE any triggered search."""
from dataclasses import replace
import time
import numpy as np
import pandas as pd
from .scenario import observe
from .robustness import truth_metrics
from floodroute.runtime import route_metrics


def route_cost(route, state, lengths, alpha):
    return float(np.sum(lengths.loc[route.edge_ids].to_numpy()*(1+alpha*state.loc[route.edge_ids].trusted_risk.to_numpy())))


class ReplayController:
    def __init__(self, runtime, policy):
        if policy not in {'never','always','triggered'}:raise ValueError('Unknown policy')
        self.runtime=runtime;self.policy=policy;self.current_route=None
        self.last_route_evaluation=None;self.last_replan_at=None;self.last_timestamp=None
        self.armed=True;self.replan_count=0;self.route_change_count=0;self.planner_calls=0
        self.lengths=runtime.edges.set_index(['u','v','key']).length_m

    def step(self, state, request):
        now=pd.Timestamp(request.timestamp);cfg=self.runtime.config; tc=cfg['trigger']
        if self.last_timestamp is not None and now<=self.last_timestamp:
            raise ValueError('Replay timestamps must increase strictly')
        self.last_timestamp=now
        reason='initial';attempt=self.current_route is None; improvement=None;switched=False
        current=None
        if self.current_route is not None:
            current=route_metrics(self.current_route,state,self.lengths,cfg['routing']['high_risk'])
            increase=current['risk_exposure']-self.last_route_evaluation['risk_exposure']
            low=current['confidence']<tc['min_confidence']
            high=current['high_risk_length_ratio']>tc['high_risk_ratio']
            rising=increase>tc['risk_increase']
            safe=(current['confidence']>tc['min_confidence']+tc['hysteresis'] and
                  current['high_risk_length_ratio']<tc['high_risk_ratio']-tc['hysteresis'])
            if safe:self.armed=True
            cooled=(now-self.last_replan_at).total_seconds()/60>=tc['cooldown_min']
            if self.policy=='always':attempt=True;reason='always'
            elif self.policy=='never':attempt=False;reason='never'
            else:
                alarm=(low or high) and self.armed or rising
                attempt=bool(alarm and cooled)
                reason=('confidence' if low else 'high_risk_ratio' if high else 'risk_increase') if attempt else 'cooldown' if alarm and not cooled else 'keep_current'
        if attempt:
            # This is the only candidate search call, after trigger evaluation.
            candidate=self.runtime.plan(state,replace(request,mode='trusted'))
            self.planner_calls+=1
            initial=self.current_route is None
            if not initial:
                self.replan_count+=1
                old_cost=route_cost(self.current_route,state,self.lengths,cfg['routing']['trusted_alpha'])
                improvement=(old_cost-route_cost(candidate,state,self.lengths,cfg['routing']['trusted_alpha']))/old_cost
            accept=initial or self.policy=='always' or improvement>=tc['minimum_improvement']
            if accept:
                switched=not initial and candidate.edge_ids!=self.current_route.edge_ids
                self.route_change_count+=int(switched)
                self.current_route=candidate
            self.last_replan_at=now;self.armed=False
        self.last_route_evaluation=route_metrics(self.current_route,state,self.lengths,cfg['routing']['high_risk'])
        return {'timestamp':now.isoformat(),'policy':self.policy,'attempted':attempt,'reason':reason,
                'candidate_improvement':improvement,'route_changed':switched,
                'replan_count':self.replan_count,'route_change_count':self.route_change_count,
                'planner_calls':self.planner_calls,'confidence':self.last_route_evaluation['confidence'],
                'observed_exposure':self.last_route_evaluation['risk_exposure'],
                'last_replan_at':self.last_replan_at.isoformat()}


def run_replay(runtime, truth, request, delay=30, missing=.2, noise=.1):
    controllers={name:ReplayController(runtime,name) for name in ['never','always','triggered']}
    rows=[];cfg=runtime.config;seed=cfg['scenario']['random_seed']
    for i,timestamp in enumerate(sorted(truth.timestamp.unique())):
        observed=observe(truth,timestamp,delay,missing,noise,seed+i)
        begin=time.perf_counter();state=runtime.observed_state(observed,timestamp)
        shared_ms=(time.perf_counter()-begin)*1000
        # Evaluation state is not supplied to controller/route search.
        truth_state=runtime.observed_state(observe(truth,timestamp,seed=seed),timestamp)
        for name,controller in controllers.items():
            begin=time.perf_counter()
            log=controller.step(state,replace(request,timestamp=timestamp.isoformat()))
            elapsed=(time.perf_counter()-begin)*1000
            rows.append({**log,**truth_metrics(controller.current_route,truth_state,controller.lengths,cfg['routing']['high_risk']),
                         'computation_ms':shared_ms+elapsed,'scenario_type':'simulated_extreme'})
        print(f'Replay {i+1}/{truth.timestamp.nunique()} complete',flush=True)
    return pd.DataFrame(rows)
