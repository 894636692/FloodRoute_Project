"""Persistent Leaflet component. Only JSON state crosses the widget boundary."""
from pathlib import Path
import streamlit.components.v1 as components

_picker = components.declare_component('leaflet_picker', path=str(Path(__file__).parent/'frontend'))

def leaflet_picker(points, response, revision, online, config, selection, timing=None,
                   key='main_route_map', on_change=None):
    """WGS84 points/GeoJSON in; clicked coordinates plus viewport and request id out.

    Static Leaflet code and display roads are browser assets, not rerun payloads.
    The component updates existing layers and never emits a complete map HTML.
    """
    markers = {k: None if not points.get(k) else {
        'lat': points[k]['snapped_lat'], 'lng': points[k]['snapped_lon']}
        for k in ('start', 'goal')}
    from floodroute.ui.map_view import route_bounds
    return _picker(markers=markers, route=response['geometry_geojson'] if response else None,
                   bounds=route_bounds(points, response), revision=str(revision),
                   online=online, center=config['map_center'], zoom=config['map_zoom'],
                   selection=selection, timing=timing or {}, default=None, key=key,
                   on_change=on_change)
