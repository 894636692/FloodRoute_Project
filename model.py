"""风险模型、路径规划和实验指标。
核心算法。包括风险计算、可信风险计算、networkx 路径规划、路线可信度判断、实验指标统计。
这里把相互关联的算法合并在一个文件中，便于初学阶段顺着数据流阅读。
后续代码规模变大时，再拆成 risk.py、routing.py 和 experiment.py。
"""

from __future__ import annotations

import math
import networkx as nx
from config import Config
from data import CityData, Point


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _freshness(age_minutes: float, tau: float) -> float:
    """信息新鲜度 F=exp(-延迟/时间尺度)。"""

    return math.exp(-age_minutes / tau) if tau > 0 else 0.0


def calculate_scores(
    city: CityData,
    observed: dict[Point, dict[str, float]],
    config: Config,
) -> dict[Point, dict[str, float]]:
    """将多源信息汇总成道路节点风险和可信风险。"""

    scores: dict[Point, dict[str, float]] = {}
    for point in city.nodes:
        static = city.features[point]
        dynamic = observed[point]

        static_risk = (
            config.elevation_weight * static["low_elevation"]
            + config.slope_weight * static["slope"]
            + config.landcover_weight * static["landcover"]
        )
        dynamic_risk = (
            config.rain_weight * dynamic["rainfall"]
            + config.water_weight * dynamic["water_level"]
        )
        risk = _clamp(static_risk + dynamic_risk)

        rain_freshness = _freshness(dynamic["age_minutes"], config.rain_tau)
        water_freshness = _freshness(dynamic["age_minutes"], config.water_tau)
        freshness = 0.4 * rain_freshness + 0.6 * water_freshness
        uncertainty = dynamic["uncertainty"]
        sensitivity = dynamic["sensitivity"]

        trusted_risk = _clamp(
            risk
            + config.uncertainty_weight * uncertainty * sensitivity
            + config.stale_weight * (1.0 - freshness) * sensitivity
        )
        scores[point] = {
            "risk": risk,
            "uncertainty": uncertainty,
            "freshness": freshness,
            "sensitivity": sensitivity,
            "trusted_risk": trusted_risk,
        }
    return scores


def _edge_cost(
    first: Point,
    second: Point,
    scores: dict[Point, dict[str, float]],
    mode: str,
    config: Config,
) -> float:
    """根据路径模式计算一条道路的代价。"""

    first_score = scores[first]
    second_score = scores[second]

    if mode == "shortest":
        return 1.0

    average_risk = (first_score["risk"] + second_score["risk"]) / 2.0
    cost = 1.0 + config.risk_weight * average_risk
    if mode == "trusted":
        average_trusted_risk = (
            first_score["trusted_risk"] + second_score["trusted_risk"]
        ) / 2.0
        cost = 1.0 + config.risk_weight * average_trusted_risk
    return cost


def plan_route(
    city: CityData,
    start: Point,
    goal: Point,
    scores: dict[Point, dict[str, float]],
    mode: str,
    config: Config,
) -> list[Point]:
    """使用 NetworkX 规划最短路、风险路或可信路。"""

    graph = nx.Graph()
    graph.add_nodes_from(city.nodes)
    for first in city.nodes:
        for second in city.neighbors[first]:
            if graph.has_edge(first, second):
                continue
            graph.add_edge(
                first,
                second,
                weight=_edge_cost(first, second, scores, mode, config),
            )

    try:
        return nx.shortest_path(graph, source=start, target=goal, weight="weight")
    except nx.NetworkXNoPath as exc:
        raise ValueError("起点和终点之间没有可通行路径") from exc


def route_metrics(
    path: list[Point],
    observed_scores: dict[Point, dict[str, float]],
    truth_scores: dict[Point, dict[str, float]],
) -> dict[str, float]:
    """用真实风险评价路线，而不是用规划时看到的旧风险评价。"""

    observed_risks = [observed_scores[node]["risk"] for node in path]
    true_risks = [truth_scores[node]["risk"] for node in path]
    return {
        "length": float(max(0, len(path) - 1)),
        "observed_risk": round(sum(observed_risks) / len(path), 4),
        "true_risk": round(sum(true_risks) / len(path), 4),
        "max_true_risk": round(max(true_risks), 4),
        "high_risk_nodes": float(sum(r >= 0.80 for r in true_risks)),
    }


def route_confidence(
    path: list[Point],
    scores: dict[Point, dict[str, float]],
) -> float:
    """路线可信度越高越好，综合考虑新鲜度和不确定性。"""

    values = [
        score["freshness"] * (1.0 - score["uncertainty"])
        for node, score in ((node, scores[node]) for node in path)
    ]
    return sum(values) / len(values)


def should_replan(
    path: list[Point],
    scores: dict[Point, dict[str, float]],
    config: Config,
) -> tuple[bool, str, float]:
    """判断当前路线是否应该触发重新规划。"""

    confidence = route_confidence(path, scores)
    max_trusted_risk = max(scores[node]["trusted_risk"] for node in path)
    if confidence < config.min_route_confidence:
        return True, "当前路线可信度低于阈值", confidence
    if max_trusted_risk >= config.high_risk_threshold:
        return True, "当前路线存在高可信风险路段", confidence
    return False, "当前路线仍然可信，保持原路线", confidence


def ascii_map(
    city: CityData,
    paths: dict[str, list[Point]],
    start: Point,
    goal: Point,
) -> str:
    """输出不依赖第三方库的终端地图，便于快速检查路线是否发生变化。"""

    marks: dict[Point, str] = {}
    symbols = {"shortest": "S", "risk": "R", "trusted": "T"}
    for name, path in paths.items():
        for node in path:
            if node not in (start, goal):
                marks[node] = symbols[name]
    marks[start] = "A"
    marks[goal] = "B"

    rows = []
    for y in range(city_height(city) - 1, -1, -1):
        rows.append(" ".join(marks.get((x, y), ".") for x in range(city_width(city))))
    return "\n".join(rows)


def city_width(city: CityData) -> int:
    return max(x for x, _ in city.nodes) + 1


def city_height(city: CityData) -> int:
    return max(y for _, y in city.nodes) + 1
