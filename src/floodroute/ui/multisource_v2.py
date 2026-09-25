"""Observed-only UI adapter for the controlled Multisource V2 scene."""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
import streamlit as st

from floodroute.runtime import ROOT
from floodroute.experiments.expanded import stable_seed
from floodroute.experiments.synthetic_water import (build_sensor_edge_mapping, map_water_sensors,
    observe_water, select_sensors, sensor_truth_table)
from floodroute.experiments.synthetic_water_v2 import simulate_latent_ponding_v2
from floodroute.risk.dynamic import map_rainfall
from floodroute.risk.fusion import ReliabilityWeightedRiskEngine
from floodroute.ui.observations import source_table
from floodroute.ui.resources import load_runtime


@st.cache_resource(show_spinner=False)
def water_bundle():
    runtime=load_runtime();cfg=json.loads((ROOT/'config/multisource_fusion_v2.json').read_text(encoding='utf-8'))
    truth=source_table('SIMULATED_SCENARIO');frames={}
    for timestamp in sorted(truth.timestamp.unique()):
        at=pd.Timestamp(timestamp); latest=truth[truth.timestamp.le(at)].sort_values(['timestamp','grid_id']).groupby('grid_id').tail(1).copy();latest['retrieved_at']=at
        mapped=map_rainfall(latest,runtime.weights,runtime.coverage,at);mapped['value']=(mapped.value/cfg['sources']['rain']['scale']).clip(0,1);frames[at]=mapped
    states,_=simulate_latent_ponding_v2(runtime.edges,frames,'ui_multisource_v2',9201,cfg['water_v2']['local_field_seed'],cfg['synthetic_water']['integration_step_min'],cfg['synthetic_water']['inflow_gain'])
    sensors=select_sensors(runtime.router.edges,cfg['synthetic_water']['sensor_selection_seed']);index=pd.MultiIndex.from_frame(runtime.edges[['u','v','key']])
    truth_table=sensor_truth_table(sensors,index,states,cfg['synthetic_water']['sensor_cadence_min'],tuple(cfg['synthetic_water']['sensor_group_offsets_min']))
    mapping=build_sensor_edge_mapping(runtime.edges,sensors,cfg['synthetic_water']['mapping_radius_m'],cfg['synthetic_water']['mapping_scale_m'])
    return cfg,sensors,truth_table,mapping,ReliabilityWeightedRiskEngine(runtime.edges,cfg,'source_specific')


def multisource_snapshot(runtime, rain_observed, timestamp, delay, missing, noise, outage_mode='正常'):
    cfg,sensors,truth_table,mapping,engine=water_bundle();at=pd.Timestamp(timestamp); kwargs={}
    east=set(sensors.nlargest(len(sensors)//2,'lon').sensor_id);times=sorted(pd.to_datetime(truth_table.timestamp).unique())
    if outage_mode=='通信中断': kwargs={'outage_sensor_ids':east,'outage_start':times[0],'outage_end':times[-1]}
    elif outage_mode=='恢复演示': kwargs={'outage_sensor_ids':east,'outage_start':times[3],'outage_end':times[min(8,len(times)-1)]}
    observed=observe_water(truth_table,at,int(delay),float(missing),float(noise),stable_seed('ui',at,delay,missing,noise,outage_mode),**kwargs)
    mapped=map_water_sensors(observed,mapping,runtime.edges,at,cfg['synthetic_water']['mapping_full_weight'])
    rain=map_rainfall(rain_observed,runtime.weights,runtime.coverage,at);state=engine.compute({'rain':rain,'water':mapped})
    available=observed[pd.to_datetime(observed.retrieved_at,utc=True).le(at)].sort_values('timestamp').groupby('sensor_id').tail(1).set_index('sensor_id')
    payload=[]
    for row in sensors.itertuples(index=False):
        if row.sensor_id in available.index:
            item=available.loc[row.sensor_id];ts=pd.Timestamp(item.timestamp);retrieved=pd.Timestamp(item.retrieved_at)
            payload.append({'sensor_id':row.sensor_id,'lon':row.lon,'lat':row.lat,'value':float(item.water_level_index),
                'timestamp':ts.isoformat(),'retrieved_at':retrieved.isoformat(),'age_min':max(0.,(at-ts).total_seconds()/60),
                'quality':str(item.quality_flag),'availability':'有效','source_type':'受控模拟'})
        else: payload.append({'sensor_id':row.sensor_id,'lon':row.lon,'lat':row.lat,'value':None,'timestamp':None,'retrieved_at':None,'age_min':None,'quality':'missing','availability':'不可用','source_type':'受控模拟'})
    return state,rain,observed,mapped,payload


def nearest_sensor(payload,lon,lat):
    if not payload:return None
    scale=111320*np.cos(np.deg2rad(lat));dist=[np.hypot((x['lon']-lon)*scale,(x['lat']-lat)*110540) for x in payload]
    item=dict(payload[int(np.argmin(dist))]);item['distance_m']=float(min(dist));return item
