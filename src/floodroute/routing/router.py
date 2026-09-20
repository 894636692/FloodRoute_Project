"""OSM MultiDiGraph routing service preserving (u, v, key)."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from uuid import uuid4

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import hashlib
from shapely.geometry import LineString, mapping

from floodroute.common.config import FloodRouteConfig
from floodroute.common.schema import DISPLAY_CRS, RouteRequest
from floodroute.risk.models import EdgeState, validate_static_edges


@dataclass
class PlannedRoute:
    route_id: str
    mode: str
    node_path: list[int]
    edge_ids: list[tuple[int, int, int]]
    distance_m: float
    travel_time_s: float
    mean_risk: float
    max_risk: float
    confidence: float
    geometry: LineString
    edge_risks: list[float]
    p95_risk: float = 0.0
    high_risk_length_ratio: float = 0.0
    freshness: float = 0.0
    uncertainty: float = 0.0
    triggered: bool = False
    trigger_reason: str = ""

    def to_response(self) -> dict:
        geojson = mapping(gpd.GeoSeries([self.geometry], crs="EPSG:32650").to_crs(DISPLAY_CRS).iloc[0])
        return {
            "route_id": self.route_id,
            "mode": self.mode,
            "distance_m": round(self.distance_m, 2),
            "travel_time_s": round(self.travel_time_s, 2),
            "mean_risk": round(self.mean_risk, 4),
            "max_risk": round(self.max_risk, 4),
            "confidence": round(self.confidence, 4),
            "p95_risk": self.p95_risk,
            "high_risk_length_ratio": self.high_risk_length_ratio,
            "freshness": self.freshness,
            "uncertainty": self.uncertainty,
            "triggered": self.triggered,
            "trigger_reason": self.trigger_reason,
            "edge_ids": [[u, v, key] for u, v, key in self.edge_ids],
            "geometry_geojson": geojson,
        }

    def write_json(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_response(), ensure_ascii=False, indent=2), encoding="utf-8")


class RoadNetworkRouter:
    def __init__(self, static_edges: gpd.GeoDataFrame, config: FloodRouteConfig | None = None) -> None:
        validate_static_edges(static_edges)
        self.config = config or FloodRouteConfig()
        self.edges = static_edges.copy()
        self.graph = nx.MultiDiGraph()
        self._build_base_graph()
        self.edge_index = pd.MultiIndex.from_frame(self.edges[['u','v','key']])
        self.edge_positions = {edge_id:i for i,edge_id in enumerate(self.edge_index)}
        self.edge_lengths = self.edges.length_m.to_numpy(float)
        nodes = {}
        for row in self.edges.itertuples():
            for node, xy in [(int(row.u),row.geometry.coords[0]),(int(row.v),row.geometry.coords[-1])]:
                if node in nodes and np.linalg.norm(np.array(nodes[node])-xy)>.01:
                    raise ValueError('Inconsistent node coordinates')
                nodes[node] = xy
        self.nodes = gpd.GeoDataFrame({'osmid':list(nodes)},
            geometry=gpd.points_from_xy([p[0] for p in nodes.values()],[p[1] for p in nodes.values()]),crs=self.edges.crs)
        self.node_index = self.nodes.sindex

    @classmethod
    def from_gpkg(cls, path: str | Path, config: FloodRouteConfig | None = None) -> "RoadNetworkRouter":
        return cls(gpd.read_file(path), config=config)

    def _build_base_graph(self) -> None:
        for row in self.edges.itertuples():
            u = int(row.u)
            v = int(row.v)
            key = int(row.key)
            length_m = float(row.length_m)
            self.graph.add_edge(
                u,
                v,
                key=key,
                length_m=length_m,
                geometry=row.geometry,
                highway=getattr(row, "highway", ""),
                oneway=getattr(row, "oneway", ""),
            )

    def nearest_node(self, lon: float, lat: float) -> int:
        if not np.isfinite([lon,lat]).all() or not (-180<=lon<=180 and -90<=lat<=90):
            raise ValueError('Invalid longitude/latitude')
        target = gpd.GeoSeries.from_xy([lon], [lat], crs=DISPLAY_CRS).to_crs(self.edges.crs).iloc[0]
        indices, distances = self.node_index.nearest(target,return_all=False,return_distance=True)
        if distances[0] > 2000:
            raise ValueError('Requested point is over 2 km from network')
        return int(self.nodes.iloc[indices[1,0]].osmid)

    def plan_frame(self, request, frame, routing_config):
        """Fast formal API: cached graph and spatial index; observed risk frame only."""
        frame=frame.reindex(self.edge_index)
        for col in ['risk','trusted_risk','risk_uncertainty','confidence']:
            if not np.isfinite(frame[col]).all():raise ValueError('Missing/nonfinite edge state: '+col)
        mode=request.mode
        column={'shortest':'risk','risk':'risk','risk_uncertainty':'risk_uncertainty','trusted':'trusted_risk'}[mode]
        alpha=routing_config['trusted_alpha'] if mode=='trusted' else routing_config['risk_alpha']
        costs=self.edge_lengths if mode=='shortest' else self.edge_lengths*(1+alpha*frame[column].to_numpy())
        def weight(u,v,choices):
            return min(costs[self.edge_positions[(u,v,k)]] for k in choices)
        start=self.nearest_node(request.start_lon,request.start_lat)
        goal=self.nearest_node(request.goal_lon,request.goal_lat)
        if start==goal:raise ValueError('Start and goal snap to the same node; choose distinct points')
        nodes=nx.shortest_path(self.graph,start,goal,weight=weight)
        ids=[];coordinates=[]
        for u,v in zip(nodes[:-1],nodes[1:]):
            key=min(self.graph[u][v],key=lambda k:costs[self.edge_positions[(u,v,k)]])
            ids.append((int(u),int(v),int(key)))
            xy=list(self.graph[u][v][key]['geometry'].coords)
            coordinates.extend(xy[1:] if coordinates else xy)
        positions=[self.edge_positions[e] for e in ids];selected=frame.iloc[positions]
        lengths=self.edge_lengths[positions];risk=selected.risk.to_numpy()
        order=np.argsort(risk); cumulative=np.cumsum(lengths[order])/lengths.sum()
        p95=risk[order][min(np.searchsorted(cumulative,.95),len(risk)-1)]
        mean=lambda col:float(np.average(selected[col],weights=lengths))
        route_id='V1-'+hashlib.sha256(json.dumps([ids,mode,request.timestamp]).encode()).hexdigest()[:12]
        return PlannedRoute(route_id,mode,list(map(int,nodes)),ids,float(lengths.sum()),
            float(lengths.sum()/routing_config['default_speed_mps']),mean('risk'),float(risk.max()),mean('confidence'),
            LineString(coordinates),list(map(float,risk)),float(p95),
            float(lengths[risk>=routing_config['high_risk']].sum()/lengths.sum()),mean('freshness'),mean('uncertainty'))

    def _weight_name(self, mode: str) -> str:
        if mode == "shortest":
            return "shortest_cost"
        if mode == "risk":
            return "risk_cost"
        if mode == "trusted":
            return "trusted_cost"
        raise ValueError(f"unknown route mode: {mode}")

    def _apply_edge_costs(self, states: dict[tuple[int, int, int], EdgeState]) -> nx.MultiDiGraph:
        graph = self.graph.copy()
        for u, v, key, data in graph.edges(keys=True, data=True):
            edge_id = (int(u), int(v), int(key))
            state = states.get(edge_id)
            if state is None:
                risk = 1.0
                trusted = 1.0
            else:
                risk = state.risk
                trusted = state.trusted_risk
            length_m = float(data["length_m"])
            data["shortest_cost"] = length_m
            data["risk_cost"] = length_m * (1.0 + self.config.routing.risk_alpha * risk)
            data["trusted_cost"] = length_m * (1.0 + self.config.routing.trusted_alpha * trusted)
        return graph

    def _edge_for_pair(self, graph: nx.MultiDiGraph, u: int, v: int, weight: str) -> tuple[int, dict]:
        candidates = graph.get_edge_data(u, v)
        if not candidates:
            raise ValueError(f"missing edge data for {u}->{v}")
        key, data = min(candidates.items(), key=lambda item: float(item[1].get(weight, float("inf"))))
        return int(key), data

    def plan(
        self,
        request: RouteRequest,
        states: dict[tuple[int, int, int], EdgeState],
    ) -> PlannedRoute:
        graph = self._apply_edge_costs(states)
        start = self.nearest_node(request.start_lon, request.start_lat)
        goal = self.nearest_node(request.goal_lon, request.goal_lat)
        weight = self._weight_name(request.mode)
        node_path = nx.shortest_path(graph, start, goal, weight=weight)

        edge_ids = []
        lines = []
        distance_m = 0.0
        risks = []
        confidences = []
        for u, v in zip(node_path[:-1], node_path[1:]):
            key, data = self._edge_for_pair(graph, u, v, weight)
            edge_id = (int(u), int(v), key)
            edge_ids.append(edge_id)
            lines.append(data["geometry"])
            distance_m += float(data["length_m"])
            state = states.get(edge_id)
            if state:
                risk_value = state.trusted_risk if request.mode == "trusted" else state.risk
                risks.append(risk_value)
                confidences.append(state.confidence)

        coordinates = []
        for line in lines:
            coords = list(line.coords)
            if coordinates and coords and coordinates[-1] == coords[0]:
                coordinates.extend(coords[1:])
            else:
                coordinates.extend(coords)
        geometry = LineString(coordinates)
        lengths = [graph[u][v][key]['length_m'] for u,v,key in edge_ids if (u,v,key) in states]
        mean_risk = float(np.average(risks, weights=lengths)) if risks else 0.0
        max_risk = max(risks) if risks else 0.0
        confidence = float(np.average(confidences, weights=lengths)) if confidences else 0.0
        return PlannedRoute(
            route_id=f"R-{uuid4().hex[:8]}",
            mode=request.mode,
            node_path=[int(node) for node in node_path],
            edge_ids=edge_ids,
            distance_m=distance_m,
            travel_time_s=distance_m / self.config.routing.default_speed_mps,
            mean_risk=mean_risk,
            max_risk=max_risk,
            confidence=confidence,
            geometry=geometry,
            edge_risks=risks,
        )
