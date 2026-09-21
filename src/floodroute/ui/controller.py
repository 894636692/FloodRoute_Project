"""Small UI state functions. Inputs are clicked WGS84 points, never latent truth."""
import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from floodroute.common.schema import RouteRequest

MODES = {'最短路径': 'shortest', '风险优先': 'risk', '可信优先': 'trusted'}
FAR_ERROR = '该位置附近没有可规划道路，请选择道路附近的位置。'


def snap_click(router, lon, lat, max_distance_m, selectable_distance_m=None):
    """Snap a WGS84 click to a motor road and retain a routable endpoint node.

    Road proximity controls UI acceptance. The displayed marker is the closest
    point on that road; ``snapped_node_id`` is the nearer endpoint used by the
    existing router. All distances are calculated in EPSG:32650 metres.
    """
    if not np.isfinite([lon, lat]).all() or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError('点击位置的经纬度无效，请重新选择。')
    target = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(router.edges.crs).iloc[0]
    indices, distances = router.edges.sindex.nearest(target, return_all=False, return_distance=True)
    road_distance = float(distances[0])
    threshold = min(float(max_distance_m), float(selectable_distance_m or max_distance_m))
    if road_distance > threshold:
        raise ValueError(FAR_ERROR)
    edge = router.edges.iloc[int(indices[1, 0])]
    projected = edge.geometry.interpolate(edge.geometry.project(target))
    start, goal = Point(edge.geometry.coords[0]), Point(edge.geometry.coords[-1])
    node_id = int(edge.u if projected.distance(start) <= projected.distance(goal) else edge.v)
    point = gpd.GeoSeries([projected], crs=router.edges.crs).to_crs(4326).iloc[0]
    return dict(clicked_lon=float(lon), clicked_lat=float(lat), snapped_node_id=node_id,
                snapped_lon=float(point.x), snapped_lat=float(point.y),
                snap_distance_m=road_distance,
                snapped_edge_id=f'{int(edge.u)}:{int(edge.v)}:{int(edge.key)}')


def can_plan(state):
    return (state.get('start') is not None and state.get('goal') is not None
            and state['start']['snapped_node_id'] != state['goal']['snapped_node_id'])


def clear_points(state, keep_result=False):
    state.update(start=None, goal=None, result=state.get('result') if keep_result else None,
                 click_error=None, click_notice=None)
    state['result_stale'] = bool(keep_result and state.get('result'))
    state['map_epoch'] = state.get('map_epoch', 0) + 1


def swap_points(state, keep_result=False):
    state['start'], state['goal'] = state.get('goal'), state.get('start')
    state['result_stale'] = bool(keep_result and state.get('result'))
    if not keep_result: state['result'] = None
    state['map_epoch'] = state.get('map_epoch', 0) + 1


def accept_click(state, router, click, selection, max_distance_m,
                 selectable_distance_m=None, keep_result=False):
    # Legacy callers can clear results; the current event consumer retains them
    # with an explicit stale flag and deduplicates without remounting the map.
    point = snap_click(router, click['lng'], click['lat'], max_distance_m, selectable_distance_m)
    state['start' if selection == '选择起点' else 'goal'] = point
    state['result_stale'] = bool(keep_result and state.get('result'))
    if not keep_result: state['result'] = None
    state['click_error'] = None
    state['click_notice'] = None
    state['map_epoch'] = state.get('map_epoch', 0) + 1
    return point


def consume_map_event(state, router, event, selection, max_distance_m,
                      selectable_distance_m=None):
    """Consume one map event without evaluating risk or searching a route.

    Rejected endpoint clicks leave endpoints, result, centre and zoom untouched.
    Information queries bypass the selectable-road threshold by design.
    """
    click=event.get('last_clicked')
    if not click:return False
    xy=(round(click['lat'],8),round(click['lng'],8))
    request_id=event.get('request_id')
    if request_id is not None and request_id == state.get('last_processed_request_id'):return False
    # Test/legacy events have no request id; ignore their carried-over coordinate.
    if request_id is None and xy == state.get('last_processed_coordinates'):return False
    state['last_processed_request_id']=request_id
    state['last_processed_coordinates']=xy
    state['last_processed_click_id']=(selection,*xy)

    if event.get('road_edge_id') or selection == '查看信息':
        state['query_point']={'lon':float(click['lng']),'lat':float(click['lat'])}
        state['query_road_edge_id']=event.get('road_edge_id')
    else:
        accept_click(state,router,click,selection,max_distance_m,
                     selectable_distance_m,keep_result=True)

    if event.get('zoom') is not None: state['map_zoom'] = event['zoom']
    bounds = event.get('bounds')
    if bounds and bounds.get('_southWest', {}).get('lat') is not None:
        state['map_bounds'] = bounds
        a,b=bounds['_southWest'],bounds['_northEast']
        state['map_center'] = [(a['lat']+b['lat'])/2,(a['lng']+b['lng'])/2]
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
