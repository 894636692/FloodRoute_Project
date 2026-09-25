"""Chinese experimental UI. Run with scripts/run_demo.py."""
from pathlib import Path
import sys
import json
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
import streamlit as st

st.set_page_config(page_title='涝途智避', layout='wide', initial_sidebar_state='expanded')
st.markdown('<style>[data-testid="stAppDeployButton"],#MainMenu,footer{display:none;}'
            '.block-container{padding-top:1.4rem;}h1{font-size:1.8rem!important;}</style>', unsafe_allow_html=True)
CFG = json.loads((ROOT / 'config/ui_v1_1.json').read_text(encoding='utf-8'))
SCENES = {'深圳真实降雨快照': 'REAL', '受控极端降雨场景': 'SIMULATED_SCENARIO',
          '异步多源机制实验': 'MULTISOURCE_V2'}
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
WATER_REASON = '当前水位数据缺少可验证的空间坐标、时间语义和测量基准，因此暂未用于道路级风险计算。'
ROAD_TYPES = {'motorway':'高速道路','motorway_link':'高速连接道路','trunk':'主干道路',
    'trunk_link':'主干连接道路','primary':'一级道路','primary_link':'一级连接道路',
    'secondary':'二级道路','secondary_link':'二级连接道路','tertiary':'三级道路',
    'tertiary_link':'三级连接道路','residential':'居住区道路','living_street':'生活街道',
    'unclassified':'一般道路','service':'服务道路'}


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
for k, value in dict(start=None, goal=None, result=None, click_error=None, click_notice=None,
                     query_point=None, query_road_edge_id=None, query_result=None,
                     result_stale=False, fit_revision=0, playback_active=False,
                     ui_sensor_payload=[]).items():
    if k not in st.session_state: st.session_state[k] = value

st.title('涝途智避')
st.caption('深圳城市内涝风险评估与应急路径规划实验系统')
with st.sidebar:
    st.header('规划条件')

# Render the shell before importing GIS resources. Resource loading runs in the
# background; the map's local assets can become interactive independently.
import pandas as pd
import networkx as nx
from time import perf_counter
from floodroute.runtime import route_metrics
from floodroute.experiments.replay import ReplayController
from floodroute.ui.controller import (MODES, can_plan, clear_points, swap_points,
    consume_map_event, complete_plan, make_request, replay_message)
from floodroute.ui.map_view import MAP_KEY
from floodroute.ui.components.leaflet_picker import leaflet_picker
from floodroute.ui.resources import (preload_runtime, edge_lengths, grid_registry,
    risk_display_edge_ids)
from floodroute.ui.observations import scenario_times, get_observations
from floodroute.ui.map_data import (build_query_result, rainfall_layer_values,
    road_risk_layer_values)
from floodroute.ui.multisource_v2 import multisource_snapshot, nearest_sensor


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


def reliable(value, pattern='{:.3f}', suffix=''):
    return '暂无可靠数据' if value is None else pattern.format(value) + suffix


def query_panel(result):
    """Render only source-backed values; ``None`` is never displayed as zero."""
    st.subheader('当前位置信息')
    location, rain = st.columns(2)
    with location:
        st.markdown('**位置**')
        st.write('查询时间：' + display_time(result['query_time']))
        st.write('最近气象格网：' + result['grid_id'])
        st.write(f"最近可规划道路距离：{result['nearest_road_distance_m']:.1f} 米")
    with rain:
        st.markdown('**降雨**')
        st.write('近1小时累计降雨：' + reliable(result['rain_mm'], '{:.1f}', ' mm'))
        st.write('数据时间：' + (display_time(result['rain_timestamp']) if result['rain_timestamp'] else '暂无可靠数据'))
        st.write('信息新鲜度：' + reliable(result['rain_freshness']))
        st.caption('数据来源：' + (result['rain_source'] or '暂无可靠数据'))
    road = result['road']
    terrain, cover, risk = st.columns(3)
    with terrain:
        st.markdown('**附近道路地形**')
        st.write('平均高程：' + reliable(road['elev_mean_m'], '{:.1f}', ' m'))
        st.write('最低高程：' + reliable(road['elev_min_m'], '{:.1f}', ' m'))
        st.write('平均坡度：' + reliable(road['slope_mean_deg'], '{:.2f}', '°'))
        st.write('低洼程度：' + reliable(road['low_elev_norm']))
        st.write('平坦度风险：' + reliable(road['flatness_risk']))
    with cover:
        st.markdown('**附近道路土地覆盖**')
        st.write('建成区比例：' + reliable(road['builtup_frac'], '{:.1%}'))
        st.write('植被比例：' + reliable(road['vegetation_frac'], '{:.1%}'))
        st.write('水体比例：' + reliable(road['water_frac'], '{:.1%}'))
        st.caption('以上为最近正式道路段缓冲区特征，不代表点击地块本身。')
    with risk:
        st.markdown('**附近道路风险**')
        st.write('静态风险：' + reliable(road['static_risk']))
        st.write('动态降雨风险：' + reliable(road['rain_risk']))
        st.write('综合风险：' + reliable(road['risk']))
        st.write('信息新鲜度：' + reliable(road['freshness']))
        st.write('不确定性：' + reliable(road['uncertainty']))
        st.write('可信风险：' + reliable(road['trusted_risk']))
    road_name = road['name'] or '暂无可靠数据'
    road_type = ROAD_TYPES.get(road['highway'], '暂无可靠数据')
    st.caption(f"道路：{road_name} ｜ 类型：{road_type} ｜ 长度：{reliable(road['length_m'], '{:.1f}', ' m')}")
    st.caption(result['water_status'], help=result['water_reason'])
    if result.get('water_sensor'):
        sensor=result['water_sensor']; st.markdown('**模拟积涝监测**')
        st.write(f"最近监测点：{sensor['sensor_id']}（{sensor['distance_m']:.0f} 米）")
        st.write('积涝状态指数：'+reliable(sensor['value']))
        st.write('观测时间：'+(display_time(sensor['timestamp']) if sensor['timestamp'] else '暂无可靠数据'))
        st.write('到达时间：'+(display_time(sensor['retrieved_at']) if sensor['retrieved_at'] else '暂无可靠数据'))
        st.write(f"状态：{sensor['availability']} ｜ 质量：{sensor['quality']}")
        st.caption('该数据为受控模拟积涝状态指数，不代表真实道路积水深度。')
    with st.expander('查询详细信息'):
        st.write(f"查询点：{result['lon']:.6f}, {result['lat']:.6f}（WGS84 / EPSG:4326）")
        st.write(f"格网中心：{result['grid_center_lon']:.6f}, {result['grid_center_lat']:.6f}")
        st.write('道路边编号：' + road['edge_id'])


@st.fragment(key='planning_workspace')
def workspace():
    # Layout placeholders exist before the first heavy resource load. Subsequent
    # interactions rerun this fragment and reuse the graph, indexes and tables.
    note_slot = st.container()
    panel_slot = st.container()
    def edit_points(action):
        action(st.session_state, keep_result=True)
        st.session_state.playback_active = False

    with st.sidebar:
        scene = st.selectbox('数据场景', list(SCENES))
        kind = SCENES[scene]
        times = scenario_times(kind)
        endpoint_status()
        selection = st.radio('选择模式', ['选择起点', '选择终点', '查看信息'])
        left, right = st.columns(2)
        left.button('清除选点', on_click=edit_points, args=(clear_points,))
        right.button('交换起终点', on_click=edit_points, args=(swap_points,))
        online = st.checkbox('在线底图', value=CFG['default_online_tiles'])
        with st.expander('地图图层', expanded=True):
            show_route = st.checkbox('当前路线', value=True)
            show_rain = st.checkbox('降雨格网', value=False)
            show_risk = st.checkbox('道路风险', value=False)
            show_sensors = st.checkbox('模拟积涝监测点', value=kind == 'MULTISOURCE_V2',
                                       disabled=kind != 'MULTISOURCE_V2')
            st.caption('降雨和风险颜色仅为地图显示分级。')
        # Changes are submitted together. Selecting a map point never submits it.
        with st.form('planning_settings', border=False):
            plan = st.form_submit_button('开始规划', type='primary', disabled=not can_plan(st.session_state))
            timestamp = st.selectbox('场景时间', times,
                                    index=len(times)-1 if kind in {'REAL', 'MULTISOURCE_V2'} else 0,
                                    format_func=display_time)
            mode = st.selectbox('路径策略', list(MODES))
            delay, missing, noise = 0, 0., 0.
            replay = False
            outage_mode = '正常'
            if kind != 'REAL':
                delay = st.slider('模拟观测延迟（分钟）', 0, 120, 30, 15)
                with st.expander('高级实验设置', expanded=False):
                    missing = st.slider('数据缺失率', 0., .8, .2, .1)
                    noise = st.slider('噪声水平', 0., .5, .1, .05)
                    if kind == 'MULTISOURCE_V2':
                        outage_mode = st.selectbox('模拟监测通信状态', ['正常','通信中断','恢复演示'])
                replay = st.form_submit_button('动态回放', disabled=not can_plan(st.session_state))
                st.caption('动态回放使用可信优先策略，保持本次地图选定的起终点。')
    signature = (kind, timestamp, mode, delay, missing, noise, outage_mode)
    if st.session_state.get('last_conditions') != signature:
        st.session_state.result_stale = st.session_state.result is not None
        st.session_state.playback_active = False
        st.session_state.last_conditions = signature
    resource_future = preload_runtime()
    need_snapshot = bool(plan or replay or show_rain or show_risk or show_sensors or
                         st.session_state.query_point)
    observed = state = mapped_rain = None
    if need_snapshot:
        runtime = resource_future.result()
        snapshot_key = (kind, str(timestamp), int(delay), float(missing), float(noise), outage_mode)
        if st.session_state.get('ui_snapshot_key') != snapshot_key:
            observed = get_observations(kind, timestamp, delay, missing, noise)
            if kind == 'MULTISOURCE_V2':
                state,mapped_rain,water_observed,mapped_water,sensor_payload=multisource_snapshot(runtime,observed,timestamp,delay,missing,noise,outage_mode)
                sources={'rain':mapped_rain}; st.session_state.ui_sensor_payload=sensor_payload
                st.session_state.ui_water_observed=water_observed; st.session_state.ui_mapped_water=mapped_water
            else:
                state, sources = runtime.observed_state_with_sources(observed, timestamp)
                st.session_state.ui_sensor_payload=[]
            st.session_state.update(ui_snapshot_key=snapshot_key, ui_observed=observed,
                                    ui_risk_state=state, ui_mapped_rain=sources['rain'],
                                    ui_rain_payload=None, ui_risk_payload=None)
        else:
            observed = st.session_state.ui_observed
            state = st.session_state.ui_risk_state
        mapped_rain = st.session_state.ui_mapped_rain
    with note_slot.container():
        with st.container(key='data_note'):
            if kind == 'REAL':
                st.info('数据说明：当前使用深圳真实气象格网降雨快照。系统输出为道路内涝风险指数，用于路径风险比较，不代表实际积水深度或道路通行安全承诺。')
                st.caption('数据来源：深圳市气象局（台） · 气象格网共 4232 个，坐标系为世界大地坐标系。')
                st.caption('观测时间：' + display_time(timestamp) + '（北京时间） · 本时次真实降雨较弱，主要用于验证真实动态数据链路。')
                st.caption('真实水位数据：未启用', help=WATER_REASON)
            elif kind == 'SIMULATED_SCENARIO':
                st.info('场景说明：当前为受控极端降雨实验。降雨变化由固定随机种子的可重复情景生成，用于测试信息延迟、不确定性和路径重规划，不代表历史实测。')
                st.caption('模拟积涝强度：仅为无物理水深含义的实验指标；本界面不显示模拟厘米水深。')
            else:
                st.info('场景说明：当前为异步多源机制实验，使用受控模拟降雨与受控模拟积涝监测。所有数值仅用于机制验证，不是历史实测。')
                c1,c2=st.columns(2); c1.metric('降雨数据','受控模拟')
                valid=sum(x.get('value') is not None for x in st.session_state.ui_sensor_payload)
                c2.metric('模拟积涝监测',f'{valid}/48 点有效')
                st.caption('积涝状态指数 0~1，不代表实际道路积水深度。')
    if plan or replay:
        lengths = edge_lengths()
    display_edges = risk_display_edge_ids() if show_risk else []

    def consume_event(event):
        wait_at = perf_counter()
        click_runtime = resource_future.result()
        wait_ms = (perf_counter()-wait_at)*1000
        started = perf_counter()
        changed = consume_map_event(st.session_state, click_runtime.router, event,
                                    event.get('selection', selection), CFG['max_snap_distance_m'],
                                    CFG['selectable_distance_m'])
        if changed:
            st.session_state.backend_timing = {'request_id': event.get('request_id', 0),
                'python_snapping_ms': (perf_counter()-started)*1000, 'resource_wait_ms': wait_ms}
        return changed

    def package(route, state, at, label, status, message=''):
        selected=state.reindex(route.edge_ids)
        fusion={'rain_freshness':float(selected.get('rain_freshness',pd.Series(1.,index=selected.index)).mean()),
                'water_freshness':None if 'water_freshness' not in selected else float(selected.water_freshness.mean()),
                'rain_effective_contribution':None if 'rain_effective_weight' not in selected else float(selected.rain_effective_weight.mean()),
                'water_effective_contribution':None if 'water_effective_weight' not in selected else float(selected.water_effective_weight.mean()),
                'fallback_fraction':None if 'fallback_static_only' not in selected else float(selected.fallback_static_only.mean())}
        return {'response': route.to_response(), 'metrics': route_metrics(route, state, lengths,
                runtime.config['routing']['high_risk']), 'timestamp': at, 'mode_label': label,
                'status': status, 'message': message, 'data_type': kind,
                'fusion': fusion,
                'selected_points': {k: dict(st.session_state[k]) for k in ('start', 'goal')}}

    rain_payload, risk_payload = [], []
    if show_rain:
        if st.session_state.get('ui_rain_payload') is None:
            st.session_state.ui_rain_payload = rainfall_layer_values(observed, timestamp)
        rain_payload = st.session_state.ui_rain_payload
    if show_risk:
        if st.session_state.get('ui_risk_payload') is None:
            st.session_state.ui_risk_payload = road_risk_layer_values(state, display_edges)
        risk_payload = st.session_state.ui_risk_payload
    if st.session_state.query_point:
        point = st.session_state.query_point
        query_key = (snapshot_key, round(point['lon'], 7), round(point['lat'], 7),
                     st.session_state.query_road_edge_id)
        if st.session_state.get('query_result_key') != query_key:
            query_at = perf_counter()
            st.session_state.query_result = build_query_result(
                runtime, grid_registry(), observed, state, mapped_rain, timestamp,
                point['lon'], point['lat'], kind, st.session_state.query_road_edge_id)
            if kind == 'MULTISOURCE_V2':
                st.session_state.query_result['water_sensor']=nearest_sensor(st.session_state.ui_sensor_payload,point['lon'],point['lat'])
                st.session_state.query_result['water_status']='模拟积涝监测：受控模拟源'
                st.session_state.query_result['water_reason']='积涝状态指数 0~1，不是实际道路水深。'
            st.session_state.query_result_key = query_key
            st.session_state.backend_timing = {
                'python_query_ms': (perf_counter()-query_at)*1000,
                'request_id': st.session_state.get('last_processed_request_id') or 0}

    try:
        if plan:
            st.session_state.playback_active = False
            with st.spinner('正在计算道路风险与路线…'):
                routing_at = perf_counter()
                route = runtime.plan(state, make_request(st.session_state, timestamp, mode))
                st.session_state.backend_timing = {'python_routing_ms': (perf_counter()-routing_at)*1000}
                complete_plan(st.session_state, package(route, state, timestamp, mode, '单次规划'))
        if replay:
            controller = ReplayController(runtime, 'triggered')
            frames = []
            view_revision = 0
            previous_geometry = None
            with st.spinner('正在准备动态回放…'):
                for at in times:
                    frame_observed = get_observations(kind, at, delay, missing, noise)
                    frame_sensors = []
                    if kind == 'MULTISOURCE_V2':
                        state, frame_rain, _, _, frame_sensors = multisource_snapshot(
                            runtime, frame_observed, at, delay, missing, noise, outage_mode)
                        frame_sources = {'rain': frame_rain}
                    else:
                        state, frame_sources = runtime.observed_state_with_sources(frame_observed, at)
                    log = controller.step(state, make_request(st.session_state, at, '可信优先'))
                    status = '已切换路线' if log['route_changed'] else '已评估候选' if log['attempted'] else '保持路线'
                    frame = package(controller.current_route, state, at, '可信优先', status, replay_message(log))
                    geometry = frame['response']['geometry_geojson']
                    if geometry != previous_geometry:
                        view_revision += 1
                        previous_geometry = geometry
                    frame['route_view_revision'] = view_revision
                    if show_rain:
                        frame['rain_layer'] = rainfall_layer_values(frame_observed, at)
                    if show_risk:
                        frame['risk_layer'] = road_risk_layer_values(state, display_edges)
                    if show_sensors:
                        frame['sensor_layer'] = frame_sensors
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
        response = result['response'] if result and not stale else None
        def on_map_change():
            try:
                changed = consume_event(st.session_state.get(MAP_KEY, {}) or {})
            except ValueError as exc:
                st.session_state.click_notice = str(exc)
                changed = True
            if changed:
                st.session_state.playback_active = False
                # Named fragment reruns are permitted from widget callbacks.
                st.rerun('planning_workspace')

        frame_rain = result.get('rain_layer', rain_payload) if result else rain_payload
        frame_risk = result.get('risk_layer', risk_payload) if result else risk_payload
        frame_sensors = result.get('sensor_layer', st.session_state.ui_sensor_payload) if result else st.session_state.ui_sensor_payload
        layer_at = result['timestamp'] if result else timestamp
        rain_meta = {'timestamp': display_time(layer_at),
                     'source': '深圳市气象局（台）' if kind == 'REAL'
                               else '受控极端降雨实验（模拟，非历史实测）'}
        event = leaflet_picker(
            st.session_state, response, revision, online, CFG, selection,
            timing=st.session_state.get('backend_timing'),
            layers={'route': show_route, 'rain': show_rain, 'road_risk': show_risk, 'sensors': show_sensors},
            rain_data=frame_rain, rain_meta=rain_meta, road_risk_data=frame_risk,
            sensor_data=frame_sensors if show_sensors else [],
            query_point=st.session_state.query_point,
            key=MAP_KEY, on_change=on_map_change)
        try:
            # An empty initial render must not wait for GIS loading.
            changed = consume_event(event) if event else False
        except ValueError as exc:
            st.session_state.click_notice = str(exc)
            changed = True
        if changed:
            st.session_state.playback_active = False
            # Fallback for an initial component value / test harness without callbacks.
            st.rerun()
        if st.session_state.click_notice:
            st.toast(st.session_state.click_notice, icon='ℹ️')
            st.session_state.click_notice = None
        if st.session_state.query_result:
            query_panel(st.session_state.query_result)
        if result:
            if result['message']: st.info(result['message'])
            st.subheader('规划结果说明')
            st.write(EXPLANATIONS[result['mode_label']])
            st.markdown('**本次规划使用的数据源**')
            if result['data_type']=='MULTISOURCE_V2':
                water_ok=any(x.get('value') is not None for x in st.session_state.ui_sensor_payload)
                st.write('降雨：有效 ｜ 模拟积涝：'+('有效' if water_ok else '当前缺失'))
                st.caption('当前路线综合使用降雨与模拟积涝监测信息计算道路风险。' if water_ok else '当前模拟积涝源不可用，系统已主要依据可用降雨信息进行风险计算。')
                with st.expander('查看融合详情'):
                    f=result['fusion']; st.write(f"Rain freshness：{f['rain_freshness']:.3f}")
                    st.write('Water freshness：'+reliable(f['water_freshness']))
                    st.write('Rain effective contribution：'+reliable(f['rain_effective_contribution']))
                    st.write('Water effective contribution：'+reliable(f['water_effective_contribution']))
                    st.write('Fallback fraction：'+reliable(f['fallback_fraction']))
            else:
                st.write('降雨：有效 ｜ 真实水位：未启用')
            with st.expander('详细风险指标'):
                m = result['metrics']
                st.write(f"最大风险：{m['max_risk']:.3f}；长度加权第九十五百分位风险：{m['p95_risk']:.3f}；高风险道路长度占比：{m['high_risk_length_ratio']:.1%}。")
            r, m = result['response'], result['metrics']
            properties = {
                'scenario': scene, 'timestamp': str(result['timestamp']),
                'strategy': result['mode_label'], 'start': result['selected_points']['start'],
                'goal': result['selected_points']['goal'], 'route': r['route_id'],
                'distance_m': r['distance_m'], 'risk_exposure': m['risk_exposure'],
                'confidence': m['confidence'], 'freshness': m['freshness'],
                'uncertainty': m['uncertainty'], 'estimated_time_s': r['travel_time_s'],
                'trigger_status': result['status'],
                'data_sources': ['深圳市气象局气象格网', '正式静态道路特征']
                    if result['data_type'] == 'REAL'
                    else ['受控极端降雨实验场景', '正式静态道路特征'],
            }
            feature = {'type': 'Feature', 'geometry': r['geometry_geojson'], 'properties': properties}
            st.download_button('下载上次路线（GeoJSON）' if stale else '下载当前路线（GeoJSON）',
                               json.dumps({'type': 'FeatureCollection', 'features': [feature]},
                                          ensure_ascii=False, default=str),
                               file_name='floodroute_route.geojson', mime='application/geo+json')
        else:
            st.caption('先在地图选择起终点，再点击“开始规划”。蓝色为起点，橙色为终点，绿色为规划路线。')
        if interval is not None and not st.session_state.playback_active:
            # Remove the timer once playback has reached the final frame.
            st.rerun()

    with panel_slot.container():
        result_panel()


workspace()
