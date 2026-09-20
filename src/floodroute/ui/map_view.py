"""Folium presentation only; online tiles are completely absent in offline mode."""
import folium


def build_map(roads, points, response, online, config):
    m = folium.Map(location=config['map_center'], zoom_start=config['map_zoom'],
                   tiles=None, prefer_canvas=True, control_scale=True)
    if online:
        folium.TileLayer('OpenStreetMap', name='在线底图').add_to(m)
    folium.GeoJson(roads, name='道路网络',
                   style_function=lambda _: {'color': '#a1a8ac', 'weight': 1, 'opacity': .65}).add_to(m)
    if response:
        folium.GeoJson(response['geometry_geojson'], name='当前路线',
                       style_function=lambda _: {'color': '#14834d', 'weight': 5}).add_to(m)
    for key, label, color in [('start', '起点', '#2474cf'), ('goal', '终点', '#e78222')]:
        point = points.get(key)
        if point:
            folium.CircleMarker([point['snapped_lat'], point['snapped_lon']], radius=7,
                                color=color, fill=True, fill_opacity=1, tooltip=label).add_to(m)
    return m
