"""Repository-relative formal data loading and observed-only route planning."""
from pathlib import Path
from types import SimpleNamespace
import json
import numpy as np
import pandas as pd
from floodroute.gis.io import read_static
from floodroute.gis.grid_mapping import fingerprint
from floodroute.dynamic.grid_source import read_rainfall
from floodroute.risk.dynamic import map_rainfall
from floodroute.risk.trusted import RiskEngine
from floodroute.routing.router import RoadNetworkRouter
from floodroute.common.schema import RouteRequest

ROOT=Path(__file__).resolve().parents[2]


def load_config(path=None):
    return json.loads(Path(path or ROOT/'config/final_v1.json').read_text(encoding='utf-8'))


class Runtime:
    def __init__(self, config=None):
        self.config=config or load_config()
        self.edges=read_static(ROOT/self.config['static_path'])
        self.weights=pd.read_parquet(ROOT/self.config['mapping_path'])
        self.weights['grid_id']=self.weights.grid_id.astype(str)
        self.coverage=pd.read_parquet(ROOT/'data/derived/mappings/edge_coverage.parquet')
        manifest=json.loads((ROOT/'data/derived/mappings/coverage_report.json').read_text())
        for path, digest in manifest['input_sha256'].items():
            if fingerprint(ROOT/path)!=digest: raise ValueError('Stale grid mapping: rebuild for '+path)
        self.engine=RiskEngine(self.edges,self.config)
        self.router=RoadNetworkRouter(self.edges)

    def observed_state(self, observed, timestamp):
        rain=map_rainfall(observed,self.weights,self.coverage,timestamp)
        return self.engine.compute({'rain':rain})

    def plan(self, state, request):
        # Explicit adapter retains B's directed routing service while migrating the engine.
        states={idx:SimpleNamespace(risk=row.risk, trusted_risk=row.trusted_risk, confidence=row.confidence)
                for idx,row in zip(state.index,state.itertuples(index=False))}
        return self.router.plan(request,states)


def route_metrics(route, state, lengths, high_risk=.65):
    """Length-weighted metrics. No truth lookup: callers choose observed or offline state."""
    selected=state.loc[route.edge_ids]
    weights=lengths.loc[route.edge_ids].to_numpy(float)
    risk=selected.risk.to_numpy(float)
    order=np.argsort(risk); cumulative=np.cumsum(weights[order])/weights.sum()
    return {'distance_m':float(weights.sum()),'risk_exposure':float(np.average(risk,weights=weights)),
            'max_risk':float(risk.max()),'p95_risk':float(risk[order][min(np.searchsorted(cumulative,.95),len(risk)-1)]),
            'high_risk_length_ratio':float(weights[risk>=high_risk].sum()/weights.sum()),
            **{col:float(np.average(selected[col],weights=weights)) for col in ['confidence','freshness','uncertainty']}}


def default_request(timestamp, mode='trusted'):
    return RouteRequest(114.030,22.535,114.090,22.570,str(timestamp),mode)


def write_json(path, data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
