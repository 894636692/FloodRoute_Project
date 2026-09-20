"""Folium presentation only; online tiles are completely absent in offline mode."""
import folium
from branca.element import MacroElement
from jinja2 import Template

MAP_KEY = 'main_route_map'


def route_bounds(points, response):
    if not response or not all(points.get(k) for k in ('start','goal')): return None
    coordinates = list(response['geometry_geojson']['coordinates'])
    for k in ('start','goal'):
        p=points[k]
        coordinates.extend([[p['snapped_lon'],p['snapped_lat']], [p['clicked_lon'],p['clicked_lat']]])
    return [[min(p[1] for p in coordinates),min(p[0] for p in coordinates)],
            [max(p[1] for p in coordinates),max(p[0] for p in coordinates)]]


class FitRouteOnce(MacroElement):
    """Existing Leaflet instance fits only a newly completed planning revision."""
    _template = Template('''{% macro script(this, kwargs) %}
    if (window.floodrouteFitRevision !== {{ this.revision|tojson }}) {
        {{ this._parent._parent.get_name() }}.fitBounds({{ this.bounds|tojson }},
            {padding: [40, 40], maxZoom: 16, animate: false});
        window.floodrouteFitRevision = {{ this.revision|tojson }};
    }
    {% endmacro %}''')
    def __init__(self,bounds,revision):
        super().__init__();self.bounds=bounds;self.revision=revision


def overlays(points, response, fit_revision=None):
    group=folium.FeatureGroup(name='起终点与路线')
    if response:
        folium.GeoJson(response['geometry_geojson'], name='当前路线',
                       style_function=lambda _: {'color': '#14834d', 'weight': 5}).add_to(group)
    for key,label,color in [('start','起点','#2474cf'),('goal','终点','#e78222')]:
        p=points.get(key)
        if p:
            folium.CircleMarker([p['snapped_lat'],p['snapped_lon']],radius=7,color=color,
                                fill=True,fill_opacity=1,tooltip=label).add_to(group)
    bounds=route_bounds(points,response)
    if fit_revision is not None and bounds:
        FitRouteOnce(bounds,str(fit_revision)).add_to(group)
    return group


def build_map(roads, points, response, online, config):
    m = folium.Map(location=config['map_center'], zoom_start=config['map_zoom'],
                   tiles=None, prefer_canvas=True, control_scale=True)
    if online:
        folium.TileLayer('OpenStreetMap', name='在线底图').add_to(m)
    elif roads:
        folium.GeoJson(roads, name='道路显示背景',
                       style_function=lambda _: {'color': '#a1a8ac', 'weight': 1, 'opacity': .65}).add_to(m)
    if points or response: overlays(points,response).add_to(m)
    return m
