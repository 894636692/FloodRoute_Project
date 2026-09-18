"""B -> C request/response route planning service."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd

from floodroute.common.config import FloodRouteConfig
from floodroute.common.schema import RouteRequest
from floodroute.risk.models import DynamicObservationMatcher, EdgeRiskEngine
from floodroute.routing.router import RoadNetworkRouter


class RoutePlanningService:
    def __init__(
        self,
        static_features_path: str | Path,
        rainfall_csv: str | None = None,
        water_level_csv: str | None = None,
        config: FloodRouteConfig | None = None,
    ) -> None:
        self.config = config or FloodRouteConfig()
        self.static_edges = gpd.read_file(static_features_path)
        self.rainfall_csv = rainfall_csv
        self.water_level_csv = water_level_csv
        self.matcher = DynamicObservationMatcher(self.config)
        self.risk_engine = EdgeRiskEngine(self.config)
        self.router = RoadNetworkRouter(self.static_edges, self.config)

    def plan(self, request: RouteRequest):
        dynamic_frame = self.matcher.attach_dynamic(
            self.static_edges,
            timestamp=request.timestamp,
            rainfall_csv=self.rainfall_csv,
            water_level_csv=self.water_level_csv,
        )
        states = self.risk_engine.build_edge_states(
            self.static_edges,
            timestamp=request.timestamp,
            dynamic_frame=dynamic_frame,
        )
        return self.router.plan(request, states)


def plan_from_files(
    request_json: str | Path,
    static_features_path: str | Path,
    output_json: str | Path,
    rainfall_csv: str | None = None,
    water_level_csv: str | None = None,
) -> dict:
    request_data = json.loads(Path(request_json).read_text(encoding="utf-8"))
    request = RouteRequest.from_dict(request_data)
    service = RoutePlanningService(
        static_features_path,
        rainfall_csv=rainfall_csv,
        water_level_csv=water_level_csv,
    )
    route = service.plan(request)
    response = route.to_response()
    Path(output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(output_json).write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    return response

