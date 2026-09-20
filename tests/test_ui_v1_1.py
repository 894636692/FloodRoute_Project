import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from v1_helpers import mini_runtime
from floodroute.ui.controller import *
from floodroute.ui.map_view import build_map
from floodroute.experiments.replay import ReplayController
from floodroute.experiments.scenario import observe
from streamlit.testing.v1 import AppTest


class ClickTests(unittest.TestCase):
    def setUp(self):
        self.runtime, self.truth, self.request = mini_runtime()
        self.a = snap_click(self.runtime.router, self.request.start_lon, self.request.start_lat, 500)
        self.b = snap_click(self.runtime.router, self.request.goal_lon, self.request.goal_lat, 500)

    def test_no_points_cannot_plan(self):
        self.assertFalse(can_plan({}))
        with self.assertRaises(ValueError): make_request({}, self.request.timestamp, '最短路径')

    def test_start_only_cannot_plan(self):
        self.assertFalse(can_plan({'start': self.a}))

    def test_complete_points_plan_on_snapped_nodes(self):
        state = {'start': self.a, 'goal': self.b}
        self.assertTrue(can_plan(state))
        req = make_request(state, self.request.timestamp, '风险优先')
        frame = self.runtime.observed_state(observe(self.truth, req.timestamp), req.timestamp)
        route = self.runtime.plan(frame, req)
        self.assertEqual(route.node_path[0], self.a['snapped_node_id'])
        self.assertEqual(route.node_path[-1], self.b['snapped_node_id'])
        self.assertLess(self.a['snap_distance_m'], .01)

    def test_clear_points(self):
        state = dict(start=self.a, goal=self.b, result=1)
        clear_points(state)
        self.assertFalse(can_plan(state)); self.assertIsNone(state['result'])

    def test_swap_points(self):
        state = dict(start=self.a, goal=self.b, result=1)
        swap_points(state)
        self.assertEqual(state['start'], self.b); self.assertEqual(state['goal'], self.a)
        self.assertIsNone(state['result'])

    def test_far_click_chinese_error_and_preserves_selection(self):
        state = dict(start=self.a)
        with self.assertRaisesRegex(ValueError, FAR_ERROR):
            accept_click(state, self.runtime.router, {'lng': 0., 'lat': 0.}, '选择起点', 500)
        self.assertEqual(state['start'], self.a)

    def test_chinese_modes(self):
        for label, mode in MODES.items():
            self.assertEqual(make_request(dict(start=self.a, goal=self.b), self.request.timestamp, label).mode, mode)

    def test_map_online_offline_difference(self):
        cfg = {'map_center': [22.55, 114.06], 'map_zoom': 12}
        roads = {'type': 'FeatureCollection', 'features': []}
        offline = build_map(roads, {}, None, False, cfg).get_root().render()
        online = build_map(roads, {}, None, True, cfg).get_root().render()
        self.assertNotIn('tile.openstreetmap.org', offline)
        self.assertIn('tile.openstreetmap.org', online)
        self.assertNotIn('L.tileLayer(', offline)

    def test_truth_never_enters_ui_planner(self):
        from floodroute.ui.observations import get_observations
        at = '2023-09-07T13:00:00+08:00'
        observed = get_observations('SIMULATED_SCENARIO', at, 30, 0, 0)
        self.assertLessEqual(observed.timestamp.max(), pd.Timestamp(at) - pd.Timedelta(minutes=30))
        self.assertNotIn('truth_risk', observed.columns)
        text = (ROOT/'src/floodroute/ui/app_v1_1.py').read_text(encoding='utf-8')
        self.assertNotIn('truth_rainfall', text)
        self.assertIn('runtime.observed_state(observed,', text)

    def test_replay_evaluates_current_before_search(self):
        r = self.runtime
        state = r.observed_state(observe(self.truth, self.request.timestamp), self.request.timestamp)
        r.config['trigger'].update(min_confidence=-1, high_risk_ratio=2, risk_increase=.08, cooldown_min=0)
        c = ReplayController(r, 'triggered'); c.step(state, self.request)
        events = []
        from floodroute.experiments import replay
        original = replay.route_metrics
        def evaluate(*args, **kwargs):
            events.append('evaluate'); return original(*args, **kwargs)
        def plan(*args, **kwargs):
            self.assertEqual(events[0], 'evaluate'); events.append('search')
            return r.router.plan_frame(args[1], args[0], r.config['routing'])
        new = state.copy(); new['risk'] = 1.
        later = replace(self.request, timestamp=(pd.Timestamp(self.request.timestamp)+pd.Timedelta(minutes=15)).isoformat())
        with patch.object(replay, 'route_metrics', side_effect=evaluate), patch.object(r, 'plan', side_effect=plan):
            log = c.step(new, later)
        self.assertTrue(log['attempted']); self.assertIn('search', events)
        with patch.object(r, 'plan', wraps=r.plan) as spy:
            c.step(new, replace(later, timestamp=(pd.Timestamp(later.timestamp)+pd.Timedelta(minutes=15)).isoformat()))
            spy.assert_not_called()


class UIChineseTests(unittest.TestCase):
    def app(self):
        return AppTest.from_file(str(ROOT/'src/floodroute/ui/app_v1_1.py'), default_timeout=90)

    def test_real_hides_simulated_parameters(self):
        with patch('streamlit_folium.st_folium', return_value={}):
            app = self.app().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.sidebar.number_input), 0)
        self.assertEqual(len(app.sidebar.slider), 0)
        self.assertEqual(len(app.metric), 7)
        self.assertTrue(next(b for b in app.sidebar.button if b.label == '开始规划').disabled)

    def test_simulated_has_delay_and_advanced_settings(self):
        with patch('streamlit_folium.st_folium', return_value={}):
            app = self.app().run()
            app.sidebar.selectbox[0].select('受控极端降雨场景').run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn('模拟观测延迟（分钟）', [w.label for w in app.sidebar.slider])
        self.assertIn('动态回放', [w.label for w in app.sidebar.button])

    def test_real_route_and_all_three_modes(self):
        with patch('streamlit_folium.st_folium', return_value={}):
            app = self.app().run()
            from floodroute.runtime import Runtime
            r = Runtime()
            for key, lon, lat in [('start', 114.030, 22.535), ('goal', 114.090, 22.570)]:
                node_id = r.router.nearest_node(lon, lat)
                point = r.router.nodes[r.router.nodes.osmid == node_id].to_crs(4326).geometry.iloc[0]
                app.session_state[key] = snap_click(r.router, point.x, point.y, 500)
            for mode in MODES:
                app.sidebar.selectbox[2].select(mode).run()
                next(b for b in app.sidebar.button if b.label == '开始规划').click().run()
                self.assertEqual(len(app.exception), 0)
                self.assertIsNotNone(app.session_state['result'])
                self.assertEqual(app.session_state['result']['response']['mode'], MODES[mode])
            app.sidebar.selectbox[0].select('受控极端降雨场景').run()
            seen = []
            original_step = ReplayController.step
            def checked_step(controller, state, request):
                seen.append((request.start_lon, request.start_lat, request.goal_lon, request.goal_lat))
                return original_step(controller, state, request)
            with patch.object(ReplayController, 'step', checked_step):
                next(b for b in app.sidebar.button if b.label == '动态回放').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(seen), 17)
            self.assertEqual(len(set(seen)), 1)
            self.assertEqual(app.session_state['result']['mode_label'], '可信优先')
            self.assertEqual(pd.Timestamp(app.session_state['result']['timestamp']).hour, 16)

if __name__ == '__main__': unittest.main()
