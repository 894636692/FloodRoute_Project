"""Chinese experimental UI. Run with scripts/run_demo.py."""
from pathlib import Path
import sys
import json
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
import pandas as pd
import streamlit as st
import networkx as nx
from streamlit_folium import st_folium
from floodroute.runtime import route_metrics
from floodroute.experiments.replay import ReplayController
from floodroute.ui.controller import (MODES, can_plan, clear_points, swap_points,
    consume_map_event, complete_plan, make_request, replay_message)
from floodroute.ui.map_view import build_map, overlays, MAP_KEY
from floodroute.ui.resources import load_runtime, edge_lengths, display_roads
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


st.markdown("""<style>
.st-key-route_metrics [data-testid="stMetricValue"],
.st-key-route_metrics [data-testid="stMetricValue"] > div {
    white-space:normal!important; overflow:visible!important;
    text-overflow:clip!important; overflow-wrap:anywhere;
    font-size:clamp(1.25rem, 2.3vw, 2.25rem)!important;
}
.st-key-route_metrics [data-testid="stMetricLabel"] {white-space:normal;}
.st-key-route_metrics [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
.st-key-route_metrics [data-testid="stColumn"] {min-width:140px;}
.st-key-data_note [data-testid="stAlert"] {padding:.4rem .7rem;}
[data-testid="stMainBlockContainer"] {min-width:0;}
iframe {max-width:100%;}
</style>""", unsafe_allow_html=True)
for k, value in dict(start=None, goal=None, result=None, click_error=None,
                     result_stale=False, fit_revision=0, playback_active=False).items():
    if k not in st.session_state: st.session_state[k] = value

st.title('涝途智避')
st.caption('深圳城市内涝风险评估与应急路径规划实验系统')


def display_time(value):
    t = pd.Timestamp(value)
    return f'{t.year}年{t.month}月{t.day}日 {t:%H:%M}'


def endpoint_status():
    for key, label in [('start', '起点'), ('goal', '终点')]:
        point = st.session_state[key]
        st.markdown('**' + label + '**')
        if point is None:
            st.caption('请在地图上选择')
        else:
            st.caption(f"✓ 已选择并吸附至道路  \n吸附距离：{point['snap_distance_m']:.0f} 米")
    with st.expander('选点详细信息'):
        for key, label in [('start', '起点'), ('goal', '终点')]:
            p = st.session_state[key]
            if p:
                st.write(f"{label}：点击经纬度 {p['clicked_lon']:.6f}, {p['clicked_lat']:.6f}；"
                         f"吸附节点编号 {p['snapped_node_id']}；吸附距离 {p['snap_distance_m']:.1f} 米。")


@st.fragment(key='planning_workspace')
def workspace():
    # Layout placeholders exist before the first heavy resource load. Subsequent
    # interactions rerun this fragment and reuse the graph, indexes and tables.
    note_slot = st.empty()
    panel_slot = st.empty()
    def edit_points(action):
        action(st.session_state, keep_result=True)
        st.session_state.playback_active = False

    with st.sidebar:
        st.header('规划条件')
        scene = st.selectbox('数据场景', list(SCENES))
        kind = SCENES[scene]
        times = scenario_times(kind)
        endpoint_status()
        selection = st.radio('选择模式', ['选择起点', '选择终点'], horizontal=True)
        left, right = st.columns(2)
        left.button('清除选点', on_click=edit_points, args=(clear_points,))
        right.button('交换起终点', on_click=edit_points, args=(swap_points,))
        online = st.checkbox('在线底图', value=CFG['default_online_tiles'])
        # Changes are submitted together. Selecting a map point never submits it.
        with st.form('planning_settings', border=False):
            plan = st.form_submit_button('开始规划', type='primary', disabled=not can_plan(st.session_state))
            timestamp = st.selectbox('场景时间', times, index=len(times)-1 if kind == 'REAL' else 0,
                                    format_func=display_time)
            mode = st.selectbox('路径策略', list(MODES))
            delay, missing, noise = 0, 0., 0.
            replay = False
            if kind != 'REAL':
                delay = st.slider('模拟观测延迟（分钟）', 0, 120, 30, 15)
                with st.expander('高级实验设置', expanded=False):
                    missing = st.slider('数据缺失率', 0., .8, .2, .1)
                    noise = st.slider('噪声水平', 0., .5, .1, .05)
                replay = st.form_submit_button('动态回放', disabled=not can_plan(st.session_state))
                st.caption('动态回放使用可信优先策略，保持本次地图选定的起终点。')
    with note_slot.container():
        with st.container(key='data_note'):
            if kind == 'REAL':
                st.info('数据说明：当前使用深圳真实气象格网降雨快照。系统输出为道路内涝风险指数，用于路径风险比较，不代表实际积水深度或道路通行安全承诺。')
                st.caption('数据来源：深圳市气象局（台） · 气象格网共 4232 个，坐标系为世界大地坐标系。')
                st.caption('观测时间：' + display_time(timestamp) + '（北京时间） · 本时次真实降雨较弱，主要用于验证真实动态数据链路。')
            else:
                st.info('场景说明：当前为受控极端降雨实验。降雨变化由固定随机种子的可重复情景生成，用于测试信息延迟、不确定性和路径重规划，不代表历史实测。')
    signature = (kind, timestamp, mode, delay, missing, noise)
    if st.session_state.get('last_conditions') != signature:
        st.session_state.result_stale = st.session_state.result is not None
        st.session_state.playback_active = False
        st.session_state.last_conditions = signature
    if not st.session_state.get('resources_ready'):
        panel_slot.markdown('**正在加载地图……**  \n路径距离：— ｜ 风险暴露：— ｜ 可信度：— ｜ 信息新鲜度：—  \n不确定性：— ｜ 预计行程：— ｜ 重规划状态：—')
    runtime = load_runtime()
    st.session_state.resources_ready = True
    lengths = edge_lengths()

    def package(route, state, at, label, status, message=''):
        return {'response': route.to_response(), 'metrics': route_metrics(route, state, lengths,
                runtime.config['routing']['high_risk']), 'timestamp': at, 'mode_label': label,
                'status': status, 'message': message, 'data_type': kind,
                'selected_points': {k: dict(st.session_state[k]) for k in ('start', 'goal')}}

    try:
        if plan:
            st.session_state.playback_active = False
            with st.spinner('正在计算道路风险与路线…'):
                observed = get_observations(kind, timestamp, delay, missing, noise)
                state = runtime.observed_state(observed, timestamp)
                route = runtime.plan(state, make_request(st.session_state, timestamp, mode))
                complete_plan(st.session_state, package(route, state, timestamp, mode, '单次规划'))
        if replay:
            controller = ReplayController(runtime, 'triggered')
            frames = []
            view_revision = 0
            previous_geometry = None
            with st.spinner('正在准备动态回放…'):
                for at in times:
                    observed = get_observations(kind, at, delay, missing, noise)
                    state = runtime.observed_state(observed, at)
                    log = controller.step(state, make_request(st.session_state, at, '可信优先'))
                    status = '已切换路线' if log['route_changed'] else '已评估候选' if log['attempted'] else '保持路线'
                    frame = package(controller.current_route, state, at, '可信优先', status, replay_message(log))
                    geometry = frame['response']['geometry_geojson']
                    if geometry != previous_geometry:
                        view_revision += 1
                        previous_geometry = geometry
                    frame['route_view_revision'] = view_revision
                    frames.append(frame)
            complete_plan(st.session_state, frames[-1])
            st.session_state.update(playback_frames=frames, playback_cursor=0, playback_active=True)
    except (ValueError, nx.NetworkXNoPath, nx.NodeNotFound):
        st.session_state.result_stale = st.session_state.result is not None
        st.error('当前条件下无法生成路线，请重新选择不同的起终点或调整场景时间。')

    # Timer redraws overlays on ONE fixed component. It never runs the planner.
    interval = CFG['replay_frame_seconds'] if st.session_state.playback_active else None
    @st.fragment(run_every=interval)
    def result_panel():
        result = st.session_state.result
        revision = str(st.session_state.fit_revision)
        if st.session_state.playback_active:
            i = st.session_state.playback_cursor
            result = st.session_state.playback_frames[i]
            st.session_state.playback_cursor += 1
            if st.session_state.playback_cursor == len(st.session_state.playback_frames):
                st.session_state.playback_active = False
        revision += f"-route-{result.get('route_view_revision', 0) if result else 0}"
        stale = st.session_state.result_stale
        if stale: st.warning('规划条件已变化，请重新规划。以下指标为上次结果。')
        values = ['—'] * 7
        if result:
            m, r = result['metrics'], result['response']
            values = [f"{r['distance_m']/1000:.2f} km", f"{m['risk_exposure']:.3f}",
                      f"{m['confidence']:.3f}", f"{m['freshness']:.3f}", f"{m['uncertainty']:.3f}",
                      f"{r['travel_time_s']/60:.1f} 分钟", result['status']]
        with st.container(key='route_metrics'):
            labels = ['路径距离', '风险暴露', '可信度', '信息新鲜度', '不确定性', '预计行程', '重规划状态']
            for start, stop in [(0, 4), (4, 7)]:
                for col, label, value in zip(st.columns(stop-start), labels[start:stop], values[start:stop]):
                    col.metric(label, value, help=HELPS.get(label))
        at = display_time(result['timestamp']) if result else '尚未规划'
        st.caption('当前结果：' + at + (' ｜ 在线底图：已开启' if online else ' ｜ 地图模式：离线实验地图'))
        # Keep the base Leaflet script invariant across click/condition updates.
        chart = build_map(None if online else display_roads(), {}, None, online, CFG)
        response = result['response'] if result and not stale else None
        group = overlays(st.session_state, response, revision if response else None)
        def on_map_change():
            try:
                changed = consume_map_event(st.session_state, runtime.router,
                    st.session_state.get(MAP_KEY, {}), selection, CFG['max_snap_distance_m'])
            except ValueError as exc:
                st.session_state.click_error = str(exc)
                changed = True
            if changed:
                st.session_state.playback_active = False
                # Named fragment reruns are permitted from widget callbacks.
                st.rerun('planning_workspace')

        restore_view = st.session_state.get('last_map_online', online) != online and not response
        st.session_state.last_map_online = online
        event = st_folium(chart, key=MAP_KEY, on_change=on_map_change, height=560, use_container_width=True,
                         feature_group_to_add=group,
                         center=st.session_state.get('map_center') if restore_view else None,
                         zoom=st.session_state.get('map_zoom') if restore_view else None,
                         returned_objects=['last_clicked', 'bounds', 'zoom'])
        try:
            changed = consume_map_event(st.session_state, runtime.router, event or {}, selection, CFG['max_snap_distance_m'])
        except ValueError as exc:
            st.session_state.click_error = str(exc)
            changed = True
        if changed:
            st.session_state.playback_active = False
            # Fallback for an initial component value / test harness without callbacks.
            st.rerun()
        if st.session_state.click_error: st.error(st.session_state.click_error)
        if result:
            if result['message']: st.info(result['message'])
            st.subheader('规划结果说明')
            st.write(EXPLANATIONS[result['mode_label']])
            with st.expander('详细风险指标'):
                m = result['metrics']
                st.write(f"最大风险：{m['max_risk']:.3f}；长度加权第九十五百分位风险：{m['p95_risk']:.3f}；高风险道路长度占比：{m['high_risk_length_ratio']:.1%}。")
            feature = {'type': 'Feature', 'geometry': result['response']['geometry_geojson'],
                       'properties': {**result['metrics'], 'mode': MODES[result['mode_label']],
                                      'data_type': result['data_type'], 'timestamp': result['timestamp'],
                                      **result['selected_points']}}
            st.download_button('下载上次路线' if stale else '下载本次路线',
                               json.dumps({'type': 'FeatureCollection', 'features': [feature]}, ensure_ascii=False),
                               file_name='floodroute_route.geojson', mime='application/geo+json')
        else:
            st.caption('先在地图选择起终点，再点击“开始规划”。蓝色为起点，橙色为终点，绿色为规划路线。')
        if interval is not None and not st.session_state.playback_active:
            # Remove the timer once playback has reached the final frame.
            st.rerun()

    with panel_slot.container():
        result_panel()


workspace()
