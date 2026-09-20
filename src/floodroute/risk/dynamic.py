"""Map available grid observations through precomputed edge intersections."""
import numpy as np
import pandas as pd

EDGE=['u','v','key']
BAD={'bad','invalid','suspect','missing','negative_rainfall','invalid_rainfall'}


def quality_penalty(flag):
    tokens=set(str(flag).lower().split(';'))
    if tokens & BAD or any(t.startswith(('invalid_', 'missing_', 'negative_')) for t in tokens):
        return 1.
    if tokens & {'retrieved_at_unknown','time_definition_user_confirmed','unknown','noisy','interpolated_observation_grid'}:
        return .5
    return 0.


def map_rainfall(observed, weights, coverage, timestamp):
    """Planner input is observed only. Latest record per grid must be available by t.

    Return indexed edge frame: value (mm/preceding hour), age_min, coverage and quality.
    Missing portions remain missing, with an explicit mapped coverage fraction.
    """
    t=pd.Timestamp(timestamp)
    if t.tzinfo is None: raise ValueError('Timezone required')
    obs=observed.copy(); obs['grid_id']=obs.grid_id.astype(str)
    obs['timestamp']=pd.to_datetime(obs.timestamp,utc=True)
    obs=obs[obs.timestamp.le(t)]
    if 'retrieved_at' in obs:
        available=pd.to_datetime(obs.retrieved_at,utc=True,errors='coerce')
        obs=obs[available.isna() | available.le(t)]
    if obs.duplicated(['grid_id','timestamp']).any():
        raise ValueError('Duplicate grid/timestamp not resolved')
    obs=obs.sort_values('timestamp').groupby('grid_id').tail(1)
    obs['age_min']=(t-obs.timestamp).dt.total_seconds()/60
    obs['quality']=obs.quality_flag.map(quality_penalty)
    bad=obs.quality_flag.map(lambda x: bool(set(str(x).lower().split(';')) & BAD))
    obs.loc[bad | ~np.isfinite(obs.rain_mm) | obs.rain_mm.lt(0),'rain_mm']=np.nan
    joined=weights.merge(obs[['grid_id','rain_mm','age_min','quality']],on='grid_id',how='left',validate='many_to_one')
    valid=joined.rain_mm.notna()
    joined['valid_weight']=joined.weight.where(valid,0)
    for src,dst in [('rain_mm','value'),('age_min','age_min'),('quality','quality')]:
        joined[dst]=joined[src].fillna(0)*joined.valid_weight
    sums=joined.groupby(EDGE)[['value','age_min','quality','valid_weight']].sum()
    for col in ['value','age_min','quality']:
        sums[col]=sums[col]/sums.valid_weight.replace(0,np.nan)
    result=coverage.set_index(EDGE)[['coverage_fraction']].join(sums)
    result['coverage']=result.coverage_fraction*result.valid_weight.fillna(0)
    return result[['value','age_min','coverage','quality']]
