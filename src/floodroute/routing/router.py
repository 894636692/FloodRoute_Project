"""OSM MultiDiGraph routing service preserving (u, v, key)."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from uuid import uuid4

import geopandas as gpd
import networkx as nx
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
        endpoints = []
        for row in self.edges.itertuples():
            endpoints.append({"osmid": int(row.u), "geometry": row.geometry.coords[0]})
            endpoints.append({"osmid": int(row.v), "geometry": row.geometry.coords[-1]})
        gdf = gpd.GeoDataFrame(
            endpoints,
            geometry=gpd.points_from_xy([item["geometry"][0] for item in endpoints], [item["geometry"][1] for item in endpoints]),
            crs=self.edges.crs,
        ).drop_duplicates("osmid")
        target = gpd.GeoSeries.from_xy([lon], [lat], crs=DISPLAY_CRS).to_crs(self.edges.crs).iloc[0]
        distances = gdf.geometry.distance(target)
        return int(gdf.loc[distances.idxmin(), "osmid"])

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
        mean_risk = sum(risks) / len(risks) if risks else 0.0
        max_risk = max(risks) if risks else 0.0
        confidence = sum(confidences) / len(confidences) if confidences else 0.0
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
