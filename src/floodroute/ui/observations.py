"""UI boundary: latent scenario is private to generation/observation simulation.

The app receives observation snapshots; no truth frame reaches its planner.
"""
import pandas as pd
from floodroute.runtime import ROOT, read_rainfall
from floodroute.experiments.scenario import observe


def scenario_times(kind):
    if kind == 'REAL':
        data = read_rainfall(ROOT / 'data/derived/dynamic/shenzhen_grid/rainfall.csv')
    else:
        data = pd.read_parquet(ROOT / 'data/scenarios/simulated_extreme/truth_rainfall.parquet', columns=['timestamp'])
    return [pd.Timestamp(t).tz_convert('Asia/Shanghai').isoformat() for t in sorted(data.timestamp.unique())]


def get_observations(kind, timestamp, delay=0, missing=0., noise=0.):
    if kind == 'REAL':
        data = read_rainfall(ROOT / 'data/derived/dynamic/shenzhen_grid/rainfall.csv')
        return data[data.timestamp <= pd.Timestamp(timestamp)].copy()
    latent = pd.read_parquet(ROOT / 'data/scenarios/simulated_extreme/truth_rainfall.parquet')
    return observe(latent, pd.Timestamp(timestamp), delay, missing, noise, 20260920)
