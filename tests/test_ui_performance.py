"""Architecture regressions; these do not claim browser/viewport acceptance."""
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from v1_helpers import mini_runtime
from floodroute.ui.controller import consume_map_event, complete_plan, clear_points, swap_points
from floodroute.ui.map_view import build_map, overlays, route_bounds, MAP_KEY
from streamlit.testing.v1 import AppTest
import streamlit_folium as sf

CFG = {'map_center': [22.55, 114.06], 'map_zoom': 12}


def component_args(points=None, response=None, revision=None, online=True):
    chart = build_map({'type':'FeatureCollection','features':[]}, {}, None, online, CFG)
    with patch.object(sf, '_component_func', return_value={}) as send:
        sf.st_folium(chart, key=MAP_KEY, feature_group_to_add=overlays(points or {}, response, revision))
    return send.call_args.kwargs


class PerformanceArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.runtime, self.truth, self.request = mini_runtime()
        self.event = {'last_clicked': {'lng': self.request.start_lon, 'lat': self.request.start_lat},
                      'zoom': 15, 'bounds': {'_southWest': {'lat':22.5,'lng':114.0},
                                            '_northEast': {'lat':22.6,'lng':114.1}}}

    def test_start_click_no_risk_or_planner(self):
        with patch.object(self.runtime, 'plan') as plan, patch.object(self.runtime, 'observed_state') as risk:
            state = {}
            self.assertTrue(consume_map_event(state,self.runtime.router,self.event,'选择起点',500))
            self.assertIn('start',state)
            plan.assert_not_called(); risk.assert_not_called()

    def test_goal_click_no_risk_or_planner(self):
        with patch.object(self.runtime, 'plan') as plan, patch.object(self.runtime, 'observed_state') as risk:
            state = {}
            consume_map_event(state,self.runtime.router,self.event,'选择终点',500)
            self.assertIn('goal',state)
            plan.assert_not_called(); risk.assert_not_called()

    def test_duplicate_click_and_mode_switch_consumed_once(self):
        state = {}
        with patch('floodroute.ui.controller.snap_click', wraps=__import__('floodroute.ui.controller',fromlist=['snap_click']).snap_click) as snap:
            consume_map_event(state,self.runtime.router,self.event,'选择起点',500)
            self.assertFalse(consume_map_event(state,self.runtime.router,self.event,'选择起点',500))
            self.assertFalse(consume_map_event(state,self.runtime.router,self.event,'选择终点',500))
            self.assertEqual(snap.call_count,1); self.assertNotIn('goal',state)

    def test_viewport_survives_selection(self):
        state = {}
        consume_map_event(state,self.runtime.router,self.event,'选择起点',500)
        self.assertEqual(state['map_zoom'],15)
        self.assertEqual(state['map_bounds'],self.event['bounds'])
        self.assertAlmostEqual(state['map_center'][0],22.55)

    def test_click_retains_previous_result_as_stale(self):
        previous={'response': 'old'}; state={'result': previous,'fit_revision': 4}
        consume_map_event(state,self.runtime.router,self.event,'选择起点',500)
        self.assertIs(state['result'],previous);self.assertTrue(state['result_stale'])
        self.assertEqual(state['fit_revision'],4)

    def test_clear_and_swap_retain_result(self):
        result={'response':'old'};state={'start':1,'goal':2,'result':result}
        swap_points(state,keep_result=True)
        self.assertEqual(state['start'],2);self.assertIs(state['result'],result)
        clear_points(state,keep_result=True)
        self.assertIsNone(state['start']);self.assertIs(state['result'],result)
        self.assertTrue(state['result_stale'])

    def test_complete_plan_advances_fit_and_keeps_endpoint_provenance(self):
        state={'start':{'snapped_node_id':1},'goal':{'snapped_node_id':2},'result_stale':True}
        complete_plan(state,{})
        self.assertFalse(state['result_stale']);self.assertEqual(state['fit_revision'],1)
        state['start']['snapped_node_id']=3
        self.assertEqual(state['result']['selected_points']['start']['snapped_node_id'],1)

    def points_and_route(self):
        p={'snapped_lon':114.05,'snapped_lat':22.55,'clicked_lon':114.04,'clicked_lat':22.54}
        q={'snapped_lon':114.08,'snapped_lat':22.58,'clicked_lon':114.09,'clicked_lat':22.59}
        return {'start':p,'goal':q},{'geometry_geojson':{'type':'LineString','coordinates':[[114.03,22.56],[114.08,22.58]]}}

    def test_component_effective_key_stable_on_click_and_plan(self):
        points,response=self.points_and_route()
        a=component_args();b=component_args(points);c=component_args(points,response,3)
        self.assertEqual(a['key'],b['key']);self.assertEqual(b['key'],c['key'])
        self.assertNotEqual(b['feature_group'],c['feature_group'])

    def test_selection_never_fits_bounds(self):
        points,_=self.points_and_route()
        args=component_args(points)
        self.assertNotIn('.fitBounds(', args['script']+args['feature_group'])

    def test_planned_route_fits_with_guard_and_padding(self):
        points,response=self.points_and_route()
        args=component_args(points,response,7)
        self.assertIn('map_div.fitBounds(',args['feature_group'])
        self.assertIn('window.floodrouteFitRevision !== "7"',args['feature_group'])
        self.assertIn('padding: [40, 40]',args['feature_group'])
        self.assertNotIn('.fitBounds(',args['script'])

    def test_bounds_include_route_clicked_and_snapped_points(self):
        points,response=self.points_and_route()
        self.assertEqual(route_bounds(points,response),[[22.54,114.03],[22.59,114.09]])
        self.assertIsNone(route_bounds({'start':points['start']},response))

    def test_online_excludes_even_supplied_road_layer(self):
        roads={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'label':'FULL_ROADS'},
               'geometry':{'type':'LineString','coordinates':[[114,22],[114.1,22.1]]}}]}
        online=build_map(roads,{},None,True,CFG).get_root().render()
        self.assertNotIn('FULL_ROADS',online);self.assertNotIn('L.geoJson(',online)
        self.assertIn('OpenStreetMap',online)

    def test_display_asset_is_small_and_separate(self):
        manifest=json.loads((ROOT/'data/derived/display/manifest.json').read_text())
        self.assertEqual(manifest['source_edges'],55727)
        self.assertLess(manifest['display_bytes'],1_000_000)
        self.assertIn('never routing',manifest['use'])

    def test_runtime_resource_cache(self):
        from floodroute.ui import resources
        resources.load_runtime.clear()
        try:
            with patch.object(resources,'Runtime',return_value=object()) as factory:
                a=resources.load_runtime();b=resources.load_runtime()
                self.assertIs(a,b);self.assertEqual(factory.call_count,1)
        finally:resources.load_runtime.clear()

    def test_dynamic_source_parsed_once_and_returns_safe_copy(self):
        from floodroute.ui import observations as obs
        obs.source_table.clear()
        try:
            with patch.object(obs,'read_rainfall',return_value=pd.DataFrame({'rain_mm':[3.]})) as read:
                a=obs.source_table('REAL');a.loc[0,'rain_mm']=9
                b=obs.source_table('REAL')
                self.assertEqual(read.call_count,1);self.assertEqual(b.loc[0,'rain_mm'],3.)
        finally:obs.source_table.clear()

    def test_app_click_then_only_submit_invokes_planner(self):
        from floodroute.ui.resources import load_runtime
        from floodroute.ui.controller import snap_click
        runtime=load_runtime()
        point=runtime.router.nodes.to_crs(4326).geometry.iloc[0]
        event={'last_clicked':{'lng':point.x,'lat':point.y}}
        with patch('streamlit_folium.st_folium',return_value=event), patch.object(runtime,'plan',wraps=runtime.plan) as plan:
            app=AppTest.from_file(str(ROOT/'src/floodroute/ui/app_v1_1.py'),default_timeout=90).run()
            self.assertEqual(len(app.exception),0)
            self.assertIsNotNone(app.session_state['start']);plan.assert_not_called()
            goal=runtime.router.nodes.to_crs(4326).geometry.iloc[100]
            app.session_state['goal']=snap_click(runtime.router,goal.x,goal.y,500)
            app.run();plan.assert_not_called()
            next(b for b in app.sidebar.button if b.label=='开始规划').click().run()
            self.assertEqual(len(app.exception),0);self.assertEqual(plan.call_count,1)


if __name__=='__main__': unittest.main()
