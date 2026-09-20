"""SIMULATED_SCENARIO generation, separate from observed-only planner modules."""
from pathlib import Path
import numpy as np
import pandas as pd


def generate_truth(grids, config):
    """Grid geometry is real; all rain values are controlled synthetic forcing.

    Values denote preceding-hour accumulation, not instantaneous rain intensity.
    The moving smooth field is a software stress scenario, not a hydrologic model.
    """
    c=config['scenario']; rng=np.random.default_rng(c['random_seed'])
    cells=grids.sort_values('grid_id').reset_index(drop=True)
    x=cells.geometry.centroid.x.to_numpy(); y=cells.geometry.centroid.y.to_numpy()
    x=(x-x.min())/(x.max()-x.min()); y=(y-y.min())/(y.max()-y.min())
    heterogeneity=rng.uniform(.85,1.15,len(cells))
    times=pd.date_range(c['start'],periods=c['steps'],freq=f"{c['step_min']}min")
    rows=[]
    for step,t in enumerate(times):
        phase=step/max(1,c['steps']-1)
        centre=.1+.8*phase
        field=np.exp(-.5*((x-centre)/c['width_fraction'])**2)
        field*=.65+.35*np.cos(np.pi*(y-.5))**2
        value=c['background_mm']+c['peak_mm']*field*heterogeneity
        rows.append(pd.DataFrame({'grid_id':cells.grid_id.astype(str),'timestamp':t,
            'window_start':t-pd.Timedelta(hours=1),'rain_mm':value,'interval_min':60,
            'quality_flag':'simulated_extreme','scenario_type':'simulated_extreme',
            'random_seed':c['random_seed']}))
    return pd.concat(rows,ignore_index=True)


def observe(truth, timestamp, delay_min=0, missing_rate=0., noise=0., seed=0):
    """Generator boundary: derives observations, never sends truth columns to planner."""
    if delay_min<0 or not 0<=missing_rate<=1 or noise<0:
        raise ValueError('Invalid observation perturbation')
    now=pd.Timestamp(timestamp)
    eligible=truth[truth.timestamp.le(now-pd.Timedelta(minutes=delay_min))]
    latest=eligible.sort_values(['timestamp','grid_id']).groupby('grid_id').tail(1).sort_values('grid_id')
    out=latest[['grid_id','timestamp','window_start','rain_mm','interval_min','quality_flag']].copy()
    rng=np.random.default_rng(seed)
    keep=rng.random(len(out))>=missing_rate
    perturbation=rng.normal(0,noise,len(out))
    out['rain_mm']=(out.rain_mm*(1+perturbation)).clip(lower=0)
    out=out.loc[keep].copy()
    if noise: out['quality_flag']=out.quality_flag+';noisy'
    out['retrieved_at']=now
    return out.reset_index(drop=True)


def save_scenario(truth, config, directory):
    from floodroute.runtime import write_json
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    truth.to_parquet(directory/'truth_rainfall.parquet',index=False)
    write_json(directory/'manifest.json',{'data_type':'SIMULATED_SCENARIO','scenario_type':'simulated_extreme',
        'geometry':'real Shenzhen grid','not_historical_observation':True,'parameters':config['scenario'],
        'truth_use':'offline evaluation and observation generation only; never planner input'})
