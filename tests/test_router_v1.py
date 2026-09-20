import sys, unittest
from pathlib import Path
from dataclasses import replace
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from v1_helpers import mini_runtime
from floodroute.experiments.scenario import observe

class RouterV1Tests(unittest.TestCase):
    def test_cache_and_weighted_metrics_and_parallel_edges(self):
        r,truth,request=mini_runtime();state=r.observed_state(observe(truth,request.timestamp),request.timestamp)
        nodes=r.router.nodes;index=r.router.node_index
        route=r.plan(state,request)
        r.plan(state,replace(request,mode='shortest'))
        self.assertIs(nodes,r.router.nodes);self.assertIs(index,r.router.node_index)
        lengths=r.edges.set_index(['u','v','key']).loc[route.edge_ids].length_m
        self.assertAlmostEqual(route.mean_risk,np.average(state.loc[route.edge_ids].risk,weights=lengths))
        self.assertGreaterEqual(route.p95_risk,route.mean_risk)
        with self.assertRaises(ValueError):r.plan(state,replace(request,goal_lon=request.start_lon,goal_lat=request.start_lat))
        with self.assertRaises(ValueError):r.router.nearest_node(0,0)

    def test_selects_lower_cost_parallel_key(self):
        from floodroute.routing.router import RoadNetworkRouter
        import pandas as pd, geopandas as gpd
        r,truth,request=mini_runtime()
        parallel=r.edges.iloc[[0]].copy();parallel['key']=1
        r.edges=gpd.GeoDataFrame(pd.concat([r.edges,parallel],ignore_index=True),crs=32650)
        r.router=RoadNetworkRouter(r.edges)
        state=pd.DataFrame(0.,index=r.router.edge_index,columns=['risk','trusted_risk','risk_uncertainty','confidence','freshness','uncertainty'])
        edge=tuple(parallel[['u','v','key']].iloc[0])
        state.loc[(edge[0],edge[1],0),'risk']=1
        ends=gpd.GeoSeries([parallel.geometry.iloc[0].interpolate(0),parallel.geometry.iloc[0].interpolate(100)],crs=32650).to_crs(4326)
        q=replace(request,start_lon=ends[0].x,start_lat=ends[0].y,goal_lon=ends[1].x,goal_lat=ends[1].y,mode='risk')
        self.assertEqual(r.plan(state,q).edge_ids,[edge])
