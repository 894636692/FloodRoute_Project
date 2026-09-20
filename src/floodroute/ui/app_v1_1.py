"""Chinese experimental UI. Run with scripts/run_demo.py."""
from pathlib import Path
import sys
import json
import time
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
import pandas as pd
import streamlit as st
import networkx as nx
from streamlit_folium import st_folium
from floodroute.runtime import Runtime, route_metrics
from floodroute.experiments.replay import ReplayController
from floodroute.ui.controller import (MODES, can_plan, clear_points, swap_points,
    accept_click, make_request, replay_message)
from floodroute.ui.map_view import build_map
from floodroute.ui.observations import scenario_times, get_observations

st.set_page_config(page_title='涝途智避', layout='wide', initial_sidebar_state='expanded')
st.markdown('<style>[data-testid="stAppDeployButton"],#MainMenu,footer{display:none;}'
            '.block-container{padding-top:1.4rem;}h1{font-size:1.8rem!important;}</style>', unsafe_allow_html=True)
CFG = json.loads((ROOT / 'config/ui_v1_1.json').read_text(encoding='utf-8'))
SCENES = {'深圳真实降雨快照': 'REAL', '受控极端降雨场景': 'SIMULATED_SCENARIO'}
EXPLANATIONS = {
    '最短路径': '当前路线仅根据道路距离规划，不主动规避内涝风险，可作为风险路径算法的对照基准。',
    '风险优先': '当前路线综合考虑道路距离和道路内涝风险，允许适度绕行，以降低整体风险暴露。',
    '可信优先': '当前路线在道路风险基础上进一步考虑动态信息的新鲜度和不确定性，优先避开风险较高或信息可信程度较低的道路。'}
HELPS = {
    '风险暴露': '当前路线按道路长度加权后的内涝风险指数，数值越低表示路线整体风险暴露越低。',
    '可信度': '根据当前动态信息的新鲜度和不确定性综合计算，仅用于不同路线和场景之间比较。',
    '信息新鲜度': '表示动态信息的时间有效程度，越接近 1 表示信息越新。',
    '不确定性': '综合反映数据质量、空间匹配和信息缺失等因素，越高表示当前判断的不确定程度越大。',
    '预计行程': '根据模型设定的道路速度估算，仅用于实验比较，不代表真实导航预计时间。'}


@st.cache_resource
def load_runtime():
    # A frozen, selected v1.1 config is used after the experiment finishes.
    path = ROOT / 'config/selected_v1_1.json'
    return Runtime(json.loads(path.read_text(encoding='utf-8')) if path.exists() else None)


@st.cache_data
def road_background():
    edges = load_runtime().router.edges
    return json.loads(edges[['geometry']].to_crs(4326).to_json())


times_for = st.cache_data(scenario_times)
observations_for = st.cache_data(get_observations)
for k, value in dict(start=None, goal=None, result=None, map_epoch=0, click_error=None).items():
    if k not in st.session_state: st.session_state[k] = value

st.title('涝途智避')
st.caption('深圳城市内涝风险评估与应急路径规划实验系统')
with st.sidebar:
    st.header('规划条件')
    scene = st.selectbox('数据场景', list(SCENES))
    kind = SCENES[scene]
    times = times_for(kind)
    timestamp = st.selectbox('场景时间', times, index=len(times)-1 if kind == 'REAL' else 0,
                            format_func=lambda t: pd.Timestamp(t).strftime('%Y年%m月%d日 %H:%M'))
    mode = st.selectbox('路径策略', list(MODES))
    for key, label in [('start', '起点'), ('goal', '终点')]:
        point = st.session_state[key]
        st.markdown('**' + label + '**')
        st.caption('请在地图上选择' if point is None else f"已选道路节点 · 吸附距离 {point['snap_distance_m']:.0f} 米")
    selection = st.radio('选择模式', ['选择起点', '选择终点'], horizontal=True)
    if st.session_state.get('last_selection') != selection:
        st.session_state.map_epoch += 1
        st.session_state.last_selection = selection
    left, right = st.columns(2)
    if left.button('清除选点'):
        clear_points(st.session_state)
        st.rerun()
    if right.button('交换起终点'):
        swap_points(st.session_state)
        st.rerun()
    delay, missing, noise = 0, 0., 0.
    if kind != 'REAL':
        delay = st.slider('模拟观测延迟（分钟）', 0, 120, 30, 15)
        with st.expander('高级实验设置', expanded=False):
            missing = st.slider('数据缺失率', 0., .8, .2, .1)
            noise = st.slider('噪声水平', 0., .5, .1, .05)
    online = st.checkbox('在线底图', value=CFG['default_online_tiles'])
    plan = st.button('开始规划', type='primary', disabled=not can_plan(st.session_state))
    replay = False
    if kind != 'REAL':
        replay = st.button('动态回放', disabled=not can_plan(st.session_state))
        st.caption('动态回放使用可信优先策略，保持本次地图选定的起终点。')

if kind == 'REAL':
    st.info('数据说明：当前使用深圳真实气象格网降雨快照。系统输出为道路内涝风险指数，用于路径风险比较，不代表实际积水深度或道路通行安全承诺。')
    st.caption('数据来源：深圳市气象局（台） · 气象格网共 4232 个，坐标系为世界大地坐标系。')
    st.caption('观测时间：' + pd.Timestamp(timestamp).strftime('%Y年%m月%d日 %H:%M') + '（北京时间）')
    st.caption('本时次真实降雨较弱，主要用于验证真实动态数据链路。')
else:
    st.info('场景说明：当前为受控极端降雨实验。降雨变化由固定随机种子的可重复情景生成，用于测试信息延迟、不确定性和路径重规划，不代表历史实测。')

signature = (kind, timestamp, mode, delay, missing, noise)
if st.session_state.get('last_conditions') != signature:
    st.session_state.result = None
    st.session_state.last_conditions = signature

runtime = load_runtime()
lengths = runtime.edges.set_index(['u', 'v', 'key']).length_m
metric_slot = st.empty()
clock_slot = st.empty()
map_slot = st.empty()
message_slot = st.empty()


def show_result(result, interactive=True, frame_key='map'):
    values = ['—'] * 7
    if result:
        m, r = result['metrics'], result['response']
        values = [f"{r['distance_m']/1000:.2f} km", f"{m['risk_exposure']:.3f}",
                  f"{m['confidence']:.3f}", f"{m['freshness']:.3f}", f"{m['uncertainty']:.3f}",
                  f"{r['travel_time_s']/60:.1f} 分钟", result['status']]
        clock_slot.caption('当前结果时间：' + pd.Timestamp(result['timestamp']).strftime('%Y年%m月%d日 %H:%M'))
    with metric_slot.container():
        for col, label, value in zip(st.columns(7),
            ['路径距离', '风险暴露', '可信度', '信息新鲜度', '不确定性', '预计行程', '重规划状态'], values):
            col.metric(label, value, help=HELPS.get(label))
    with map_slot.container():
        st.caption('在线底图已开启' if online else '当前为离线实验地图模式')
        chart = build_map(road_background(), st.session_state, result['response'] if result else None, online, CFG)
        event = st_folium(chart, key=f'{frame_key}_{st.session_state.map_epoch}_{selection}_{online}',
                         height=510, use_container_width=True,
                         returned_objects=['last_clicked'] if interactive else [])
    return event.get('last_clicked') if event else None


def package(route, state, at, label, status, message=''):
    return {'response': route.to_response(), 'metrics': route_metrics(route, state, lengths,
            runtime.config['routing']['high_risk']), 'timestamp': at, 'mode_label': label,
            'status': status, 'message': message}


try:
    if plan:
        with st.spinner('正在计算道路风险与路线…'):
            observed = observations_for(kind, timestamp, delay, missing, noise)
            state = runtime.observed_state(observed, timestamp)
            request = make_request(st.session_state, timestamp, mode)
            route = runtime.plan(state, request)
            st.session_state.result = package(route, state, timestamp, mode, '单次规划')
    if replay:
        controller = ReplayController(runtime, 'triggered')
        for index, at in enumerate(times):
            observed = observations_for(kind, at, delay, missing, noise)
            state = runtime.observed_state(observed, at)
            log = controller.step(state, make_request(st.session_state, at, '可信优先'))
            status = '已切换路线' if log['route_changed'] else '已评估候选' if log['attempted'] else '保持路线'
            result = package(controller.current_route, state, at, '可信优先', status, replay_message(log))
            show_result(result, interactive=False, frame_key=f'replay_{index}')
            message_slot.info(result['message'])
            time.sleep(CFG['replay_frame_seconds'])
        st.session_state.result = result
        # A fresh render after playback avoids duplicate component IDs.
        st.rerun()
except (ValueError, nx.NetworkXNoPath, nx.NodeNotFound):
    st.session_state.result = None
    message_slot.error('当前条件下无法生成路线，请重新选择不同的起终点或调整场景时间。')

result = st.session_state.result
click = show_result(result)
if click:
    try:
        accept_click(st.session_state, runtime.router, click, selection, CFG['max_snap_distance_m'])
    except ValueError as exc:
        st.session_state.click_error = str(exc)
        st.session_state.map_epoch += 1
    st.rerun()
if st.session_state.click_error: st.error(st.session_state.click_error)
if result:
    if result['message']: message_slot.info(result['message'])
    st.subheader('规划结果说明')
    st.write(EXPLANATIONS[result['mode_label']])
    with st.expander('详细风险指标'):
        m = result['metrics']
        st.write(f"最大风险：{m['max_risk']:.3f}；长度加权第九十五百分位风险：{m['p95_risk']:.3f}；高风险道路长度占比：{m['high_risk_length_ratio']:.1%}。")
    feature = {'type': 'Feature', 'geometry': result['response']['geometry_geojson'],
               'properties': {**result['metrics'], 'mode': MODES[result['mode_label']], 'data_type': kind,
                              'timestamp': result['timestamp'], 'start': st.session_state.start, 'goal': st.session_state.goal}}
    st.download_button('下载本次路线', json.dumps({'type': 'FeatureCollection', 'features': [feature]}, ensure_ascii=False),
                       file_name='floodroute_route.geojson', mime='application/geo+json')
else:
    st.caption('先在地图选择起终点，再点击“开始规划”。蓝色为起点，橙色为终点，绿色为规划路线。')
