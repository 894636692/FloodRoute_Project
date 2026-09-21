"""Cached UI resources only. Formal geometry and algorithm inputs are unchanged."""
import json
import pandas as pd
import streamlit as st
from floodroute.runtime import ROOT, Runtime
from floodroute.ui.map_data import read_display_edge_ids

LOAD_COUNTS = {'runtime': 0, 'display': 0}


@st.cache_resource(show_spinner=False)
def preload_runtime():
    """Share one background load; only a click/plan waits if it is still running."""
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='floodroute-load')
    future = pool.submit(load_runtime)
    future.add_done_callback(lambda _: pool.shutdown(wait=False))
    return future


@st.cache_resource(show_spinner=False)
def load_runtime():
    LOAD_COUNTS['runtime'] += 1
    path = ROOT/'config/selected_v1_1.json'
    return Runtime(json.loads(path.read_text(encoding='utf-8')) if path.exists() else None)


@st.cache_resource(show_spinner=False)
def edge_lengths():
    return load_runtime().edges.set_index(['u','v','key']).length_m


@st.cache_data(show_spinner=False)
def display_roads():
    LOAD_COUNTS['display'] += 1
    return json.loads((ROOT/'data/derived/display/roads_display.geojson').read_text(encoding='utf-8'))


@st.cache_data(show_spinner=False)
def grid_registry():
    """Official WGS84 grid centres; returned copies are safe for UI queries."""
    return pd.read_csv(ROOT/'data/derived/dynamic/shenzhen_grid/grid_cells.csv')[
        ['grid_id', 'lon', 'lat', 'source', 'quality_flag']]


@st.cache_data(show_spinner=False)
def risk_display_edge_ids():
    """IDs represented by the browser-only simplified risk geometry."""
    return read_display_edge_ids(
        ROOT/'src/floodroute/ui/components/leaflet_picker/frontend/risk_roads_display.geojson')
