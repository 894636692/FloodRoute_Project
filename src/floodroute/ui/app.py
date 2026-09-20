"""Local UI: real snapshots and explicitly simulated scenarios."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
import pandas as pd
import geopandas as gpd
import pydeck as pdk
import streamlit as st
import networkx as nx
from floodroute.runtime import Runtime,read_rainfall,route_metrics
from floodroute.common.schema import RouteRequest
from floodroute.experiments.scenario import observe

st.set_page_config(page_title='涝途智避 · FloodRoute',page_icon='🌧️',layout='wide')


@st.cache_resource
def load_runtime():
    return Runtime()


@st.cache_data
def load_observations(kind):
    if kind=='REAL':return read_rainfall(ROOT/'data/derived/dynamic/shenzhen_grid/rainfall.csv')
    return pd.read_parquet(ROOT/'data/scenarios/simulated_extreme/truth_rainfall.parquet')


@st.cache_data
def road_background():
    r=load_runtime()
    major=r.router.edges[r.router.edges.highway.isin(['primary','secondary','trunk','motorway','tertiary'])]
    return json.loads(major[['geometry']].to_crs(4326).to_json())


st.title('涝途智避')
st.caption('FloodRoute v1 · 深圳道路风险与可信路径实验')
st.info('输出为道路内涝风险指数，不是积水深度或通行安全承诺。真实水位源未启用。')
with st.sidebar:
    st.header('规划条件')
    kind=st.selectbox('数据场景',['REAL','SIMULATED_SCENARIO'],format_func=lambda x:'真实深圳降雨 · REAL' if x=='REAL' else '受控极端情景 · SIMULATED')
    data=load_observations(kind)
    times=[pd.Timestamp(t).tz_convert('Asia/Shanghai').isoformat() for t in sorted(data.timestamp.unique())]
    timestamp=st.selectbox('时间（北京时间）',times,index=len(times)-1 if kind=='REAL' else len(times)//2)
    mode=st.selectbox('路径策略',['shortest','risk','trusted'])
    start_lon=st.number_input('起点经度',value=114.030,format='%.5f')
    start_lat=st.number_input('起点纬度',value=22.535,format='%.5f')
    goal_lon=st.number_input('终点经度',value=114.090,format='%.5f')
    goal_lat=st.number_input('终点纬度',value=22.570,format='%.5f')
    delay=st.slider('模拟观测延迟（分钟）',0,120,30,15,disabled=kind=='REAL')
    tiles=st.checkbox('显示在线底图',value=False,help='不勾选时显示本地道路轮廓，地图不依赖在线瓦片。')
    st.caption('起终点将吸附到候选机动车路网。旅行时间按固定 8 m/s 估算。')

if kind=='SIMULATED_SCENARIO':
    st.warning('SIMULATED_SCENARIO：雨量来自固定种子的受控情景，不是 2023 年历史实测。')
    observed=observe(data,pd.Timestamp(timestamp),delay,.2,.1,20260920)
else:
    observed=data
    st.caption('REAL：当前真实样本的前一小时累计降雨均为 0 mm；时间定义由项目负责人确认，获取时间未知。')

try:
    with st.spinner('读取道路并计算当前观测风险…'):
        runtime=load_runtime()
        state=runtime.observed_state(observed,timestamp)
        request=RouteRequest(start_lon,start_lat,goal_lon,goal_lat,timestamp,mode)
        route=runtime.plan(state,request)
        lengths=runtime.edges.set_index(['u','v','key']).length_m
        metrics=route_metrics(route,state,lengths,runtime.config['routing']['high_risk'])
        response=route.to_response()
    columns=st.columns(6)
    for col,label,value in zip(columns,['距离','风险暴露','可信度指数','新鲜度','不确定性','估计行程'],
        [f"{route.distance_m/1000:.2f} km",f"{metrics['risk_exposure']:.3f}",f"{metrics['confidence']:.3f}",
         f"{metrics['freshness']:.3f}",f"{metrics['uncertainty']:.3f}",f"{route.travel_time_s/60:.1f} min"]):
        col.metric(label,value)
    coordinates=response['geometry_geojson']['coordinates']
    layers=[pdk.Layer('GeoJsonLayer',data=road_background(),get_line_color=[160,173,185],line_width_min_pixels=1),
            pdk.Layer('PathLayer',data=[{'path':coordinates}],get_path='path',get_color=[0,143,130],width_min_pixels=5),
            pdk.Layer('ScatterplotLayer',data=[{'position':[start_lon,start_lat],'color':[30,120,230]},
                {'position':[goal_lon,goal_lat],'color':[235,100,50]}],get_position='position',get_fill_color='color',radius_min_pixels=7)]
    st.pydeck_chart(pdk.Deck(layers=layers,map_provider='carto' if tiles else None,
        map_style=pdk.map_styles.LIGHT if tiles else None,
        initial_view_state=pdk.ViewState(latitude=(start_lat+goal_lat)/2,longitude=(start_lon+goal_lon)/2,zoom=12)),height=520)
    st.caption('蓝点为请求起点，橙点为请求终点，绿色为吸附到路网后的路线；地图使用 WGS84，距离按 UTM 50N 计算。')
    st.download_button('下载本次路线 GeoJSON',json.dumps({'type':'FeatureCollection','features':[{'type':'Feature',
        'geometry':response['geometry_geojson'],'properties':{**metrics,'mode':mode,'timestamp':timestamp,'data_type':kind}}]},ensure_ascii=False),
        file_name='floodroute_route.geojson',mime='application/geo+json')
except (ValueError,nx.NetworkXNoPath,nx.NodeNotFound) as exc:
    st.error(f'无法生成路线：{exc}')

with st.expander('Trigger 时间序列实验记录'):
    st.caption('预先计算的固定起终点实验，30 分钟延迟、20% 缺失、10% 噪声；与上方自由选择的单次规划分开。')
    file=ROOT/'results/trigger_replay/replay.csv'
    if file.exists():
        table=pd.read_csv(file)
        st.dataframe(table[['timestamp','policy','reason','attempted','route_changed','replan_count','route_change_count','truth_exposure']],hide_index=True)
    else:st.info('运行 python scripts/run_trigger_replay.py 后显示实验记录。')
