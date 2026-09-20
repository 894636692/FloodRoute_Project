"""Cached UI resources only. Formal geometry and algorithm inputs are unchanged."""
import json
import streamlit as st
from floodroute.runtime import ROOT, Runtime

LOAD_COUNTS = {'runtime': 0, 'display': 0}


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
