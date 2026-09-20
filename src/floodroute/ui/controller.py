"""Small UI state functions. Inputs are clicked WGS84 points, never latent truth."""
import geopandas as gpd
import numpy as np
from floodroute.common.schema import RouteRequest

MODES = {'最短路径': 'shortest', '风险优先': 'risk', '可信优先': 'trusted'}
FAR_ERROR = '所选位置距离可规划道路较远，请重新选择靠近道路的位置。'


def snap_click(router, lon, lat, max_distance_m):
    """Return clicked/snapped WGS84 coordinates and distance measured in UTM metres.

    Reuses the router's existing motor-road node table and spatial index.
    """
    if not np.isfinite([lon, lat]).all() or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError('点击位置的经纬度无效，请重新选择。')
    target = gpd.GeoSeries.from_xy([lon], [lat], crs=4326).to_crs(32650).iloc[0]
    indices, distances = router.node_index.nearest(target, return_all=False, return_distance=True)
    if distances[0] > max_distance_m:
        raise ValueError(FAR_ERROR)
    node = router.nodes.iloc[indices[1, 0]]
    point = gpd.GeoSeries([node.geometry], crs=32650).to_crs(4326).iloc[0]
    return dict(clicked_lon=float(lon), clicked_lat=float(lat), snapped_node_id=int(node.osmid),
                snapped_lon=point.x, snapped_lat=point.y, snap_distance_m=float(distances[0]))


def can_plan(state):
    return (state.get('start') is not None and state.get('goal') is not None
            and state['start']['snapped_node_id'] != state['goal']['snapped_node_id'])


def clear_points(state, keep_result=False):
    state.update(start=None, goal=None, result=state.get('result') if keep_result else None, click_error=None)
    state['result_stale'] = bool(keep_result and state.get('result'))
    state['map_epoch'] = state.get('map_epoch', 0) + 1


def swap_points(state, keep_result=False):
    state['start'], state['goal'] = state.get('goal'), state.get('start')
    state['result_stale'] = bool(keep_result and state.get('result'))
    if not keep_result: state['result'] = None
    state['map_epoch'] = state.get('map_epoch', 0) + 1


def accept_click(state, router, click, selection, max_distance_m, keep_result=False):
    # Legacy callers can clear results; the current event consumer retains them
    # with an explicit stale flag and deduplicates without remounting the map.
    point = snap_click(router, click['lng'], click['lat'], max_distance_m)
    state['start' if selection == '选择起点' else 'goal'] = point
    state['result_stale'] = bool(keep_result and state.get('result'))
    if not keep_result: state['result'] = None
    state['click_error'] = None
    state['map_epoch'] = state.get('map_epoch', 0) + 1
    return point


def consume_map_event(state, router, event, selection, max_distance_m):
    """Consume each coordinate event once; never evaluate risk or search a route."""
    if event.get('zoom') is not None: state['map_zoom'] = event['zoom']
    bounds = event.get('bounds')
    if bounds and bounds.get('_southWest', {}).get('lat') is not None:
        state['map_bounds'] = bounds
        a,b=bounds['_southWest'],bounds['_northEast']
        state['map_center'] = [(a['lat']+b['lat'])/2,(a['lng']+b['lng'])/2]
    click=event.get('last_clicked')
    if not click:return False
    xy=(round(click['lat'],8),round(click['lng'],8))
    # Ignore the carried-over coordinate even when selection mode changes.
    if xy == state.get('last_processed_coordinates'):return False
    state['last_processed_coordinates']=xy
    state['last_processed_click_id']=(selection,*xy)
    accept_click(state,router,click,selection,max_distance_m,keep_result=True)
    return True


def complete_plan(state, result):
    state['result']=result
    state['result_stale']=False
    state['fit_revision']=state.get('fit_revision',0)+1
    # Preserve provenance if endpoints are edited while the old result is retained.
    result['selected_points']={k:dict(state[k]) for k in ('start','goal')}


def make_request(state, timestamp, label):
    if not can_plan(state):
        raise ValueError('请在地图上选择不同的起点和终点。')
    a, b = state['start'], state['goal']
    return RouteRequest(a['snapped_lon'], a['snapped_lat'], b['snapped_lon'], b['snapped_lat'],
                        timestamp, MODES[label])


def planning_observations(provider, kind, timestamp, delay, missing, noise):
    """Provider returns only observations available at this decision time."""
    return provider(kind, timestamp, delay, missing, noise)


def replay_message(log):
    if log['reason'] == 'initial': return '已生成初始路线。'
    if log['route_changed']:
        return '检测到当前路线风险状态发生明显变化，已触发重新规划。已切换至新的低风险路线。'
    if log['attempted']:
        return '检测到当前路线风险状态发生明显变化，已触发重新规划。已完成候选路线评估，改善幅度不足，继续保持当前路线。'
    return '当前路线状态保持稳定，继续保持当前路线。'
