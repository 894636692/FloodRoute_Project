"""UI boundary: latent scenario is private to generation/observation simulation.

The app receives observation snapshots; no truth frame reaches its planner.
"""
import pandas as pd
import streamlit as st
from floodroute.runtime import ROOT, read_rainfall
from floodroute.experiments.scenario import observe


TABLE_LOAD_COUNTS = {'REAL': 0, 'SIMULATED_SCENARIO': 0}


@st.cache_data(show_spinner=False)
def source_table(kind):
    TABLE_LOAD_COUNTS[kind] += 1
    if kind == 'REAL':
        return read_rainfall(ROOT / 'data/derived/dynamic/shenzhen_grid/rainfall.csv')
    return pd.read_parquet(ROOT / 'data/scenarios/simulated_extreme/truth_rainfall.parquet')


@st.cache_data(show_spinner=False)
def scenario_times(kind):
    data = source_table(kind)
    return [pd.Timestamp(t).tz_convert('Asia/Shanghai').isoformat() for t in sorted(data.timestamp.unique())]


@st.cache_data(show_spinner=False)
def get_observations(kind, timestamp, delay=0, missing=0., noise=0.):
    if kind == 'REAL':
        data = source_table(kind)
        return data[data.timestamp <= pd.Timestamp(timestamp)].copy()
    latent = source_table(kind)
    return observe(latent, pd.Timestamp(timestamp), delay, missing, noise, 20260920)
