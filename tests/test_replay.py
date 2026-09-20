import sys,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from v1_helpers import mini_runtime
from floodroute.experiments.scenario import observe
from floodroute.experiments.replay import ReplayController,run_replay

class ReplayTests(unittest.TestCase):
    def test_no_search_before_trigger_and_cooldown(self):
        r,truth,request=mini_runtime();r.config['trigger'].update(min_confidence=-1,high_risk_ratio=2,risk_increase=2)
        state=r.observed_state(observe(truth,request.timestamp),request.timestamp)
        control=ReplayController(r,'triggered')
        with patch.object(r,'plan',wraps=r.plan) as spy:
            control.step(state,request)
            later=replace(request,timestamp=(pd.Timestamp(request.timestamp)+pd.Timedelta(minutes=15)).isoformat())
            control.step(state,later)
            self.assertEqual(spy.call_count,1)
            with self.assertRaises(ValueError):control.step(state,later)

    def test_confidence_triggers_candidate_only_after_cooldown(self):
        r,truth,request=mini_runtime();state=r.observed_state(observe(truth,request.timestamp),request.timestamp)
        c=ReplayController(r,'triggered');c.step(state,request)
        c.armed=True;state=state.copy();state['confidence']=0
        a=c.step(state,replace(request,timestamp=(pd.Timestamp(request.timestamp)+pd.Timedelta(minutes=15)).isoformat()))
        self.assertFalse(a['attempted'])
        b=c.step(state,replace(request,timestamp=(pd.Timestamp(request.timestamp)+pd.Timedelta(minutes=30)).isoformat()))
        self.assertTrue(b['attempted']);self.assertEqual(c.planner_calls,2)
        self.assertFalse(b['route_changed'])

    def test_chronological_policy_comparison(self):
        r,truth,request=mini_runtime()
        rows=run_replay(r,truth,request)
        last=rows.groupby('policy').tail(1).set_index('policy')
        self.assertEqual(last.loc['never','planner_calls'],1)
        self.assertEqual(last.loc['always','planner_calls'],17)
        self.assertLessEqual(last.loc['triggered','planner_calls'],17)
        self.assertEqual(rows.timestamp.nunique(),17)
