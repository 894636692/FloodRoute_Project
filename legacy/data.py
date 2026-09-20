"""数据层。

当前使用可重复生成的样例城市数据，目的是先验证完整算法链路。
后续可以把 build_demo_city() 替换为 DEM、WorldCover、OSM 和真实接口读取。
"""

from dataclasses import dataclass
import csv
import math
from pathlib import Path
import random

Point = tuple[int, int]


@dataclass
class CityData:
    nodes: list[Point]
    neighbors: dict[Point, list[Point]]
    features: dict[Point, dict[str, float]]
    ground_truth: dict[Point, dict[str, float]]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _flood_corridor(point: Point, width: int, height: int) -> bool:
    """样例中的积涝高风险路段，横穿起点和终点之间的直线路径。"""

    x, y = point
    center_y = height // 2
    return 5 <= x <= width - 6 and abs(y - center_y) <= 1


def build_demo_city(width: int = 15, height: int = 15, seed: int = 7) -> CityData:
    """生成一个规则路网和一片可解释的高风险积涝走廊。"""

    rng = random.Random(seed)
    nodes = [(x, y) for y in range(height) for x in range(width)]
    neighbors: dict[Point, list[Point]] = {node: [] for node in nodes}

    # 只连接上下左右，等价于一个最简单的城市路网。
    for x, y in nodes:
        for candidate in ((x + 1, y), (x, y + 1), (x - 1, y), (x, y - 1)):
            if candidate in neighbors:
                neighbors[(x, y)].append(candidate)

    features: dict[Point, dict[str, float]] = {}
    ground_truth: dict[Point, dict[str, float]] = {}

    for point in nodes:
        x, y = point
        in_corridor = _flood_corridor(point, width, height)
        distance_from_center = abs(y - height / 2) / max(1.0, height / 2)

        # 数值均已归一化到 0~1，便于直接解释和替换成真实栅格统计值。
        low_elevation = _clamp(
            0.20 + 0.35 * (1.0 - distance_from_center)
            + (0.35 if in_corridor else 0.0)
        )
        slope = _clamp(0.15 + 0.45 * rng.random() + (0.10 if in_corridor else 0.0))
        landcover = _clamp(0.25 + 0.35 * rng.random())

        rainfall = _clamp(0.20 + 0.08 * rng.random() + (0.65 if in_corridor else 0.0))
        water_level = _clamp(0.12 + 0.08 * rng.random() + (0.78 if in_corridor else 0.0))

        features[point] = {
            "low_elevation": low_elevation,
            "slope": slope,
            "landcover": landcover,
        }
        ground_truth[point] = {
            "rainfall": rainfall,
            "water_level": water_level,
        }

    return CityData(nodes, neighbors, features, ground_truth)


def load_city_from_csv(nodes_csv: str | Path, edges_csv: str | Path) -> CityData:
    """Load a small real-data trial from two CSV files.

    nodes_csv columns:
    x,y,low_elevation,slope,landcover,rainfall_truth,water_level_truth

    edges_csv columns:
    from_x,from_y,to_x,to_y

    All risk-related values should be normalized to 0~1 before loading.
    """

    nodes_path = Path(nodes_csv)
    edges_path = Path(edges_csv)
    features: dict[Point, dict[str, float]] = {}
    ground_truth: dict[Point, dict[str, float]] = {}

    with nodes_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {
            "x",
            "y",
            "low_elevation",
            "slope",
            "landcover",
            "rainfall_truth",
            "water_level_truth",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{nodes_path} 缺少字段: {', '.join(sorted(missing))}")

        for row in reader:
            point = (int(row["x"]), int(row["y"]))
            features[point] = {
                "low_elevation": _clamp(float(row["low_elevation"])),
                "slope": _clamp(float(row["slope"])),
                "landcover": _clamp(float(row["landcover"])),
            }
            ground_truth[point] = {
                "rainfall": _clamp(float(row["rainfall_truth"])),
                "water_level": _clamp(float(row["water_level_truth"])),
            }

    nodes = list(features)
    neighbors: dict[Point, list[Point]] = {node: [] for node in nodes}
    with edges_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {"from_x", "from_y", "to_x", "to_y"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{edges_path} 缺少字段: {', '.join(sorted(missing))}")

        for row in reader:
            first = (int(row["from_x"]), int(row["from_y"]))
            second = (int(row["to_x"]), int(row["to_y"]))
            if first not in neighbors or second not in neighbors:
                raise ValueError(f"{edges_path} 中的边引用了 nodes.csv 不存在的节点")
            neighbors[first].append(second)
            neighbors[second].append(first)

    return CityData(nodes, neighbors, features, ground_truth)


def load_observed_from_csv(
    city: CityData,
    observed_csv: str | Path,
    default_delay_minutes: int = 0,
) -> dict[Point, dict[str, float]]:
    """Load observed dynamic data from CSV.

    observed_csv columns:
    x,y,rainfall_observed,water_level_observed,age_minutes,uncertainty,sensitivity

    Missing rows fall back to ground truth with low uncertainty.
    """

    observed = {
        point: {
            "rainfall": truth["rainfall"],
            "water_level": truth["water_level"],
            "age_minutes": float(default_delay_minutes),
            "uncertainty": min(1.0, 0.08 + default_delay_minutes / 150.0),
            "sensitivity": 0.1,
        }
        for point, truth in city.ground_truth.items()
    }

    observed_path = Path(observed_csv)
    with observed_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {
            "x",
            "y",
            "rainfall_observed",
            "water_level_observed",
            "age_minutes",
            "uncertainty",
            "sensitivity",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{observed_path} 缺少字段: {', '.join(sorted(missing))}")

        for row in reader:
            point = (int(row["x"]), int(row["y"]))
            if point not in observed:
                raise ValueError(f"{observed_path} 中存在 nodes.csv 没有的节点: {point}")
            observed[point] = {
                "rainfall": _clamp(float(row["rainfall_observed"])),
                "water_level": _clamp(float(row["water_level_observed"])),
                "age_minutes": float(row["age_minutes"]),
                "uncertainty": _clamp(float(row["uncertainty"])),
                "sensitivity": _clamp(float(row["sensitivity"])),
            }
    return observed


def make_observed_data(city: CityData, delay_minutes: int) -> dict[Point, dict[str, float]]:
    """生成算法真正能看到的动态数据。

    为了模拟现实中的信息延迟，高风险走廊在延迟场景中保留较低的旧观测值。
    算法只能使用这里返回的 observed 数据，不能直接读取 ground_truth。
    """

    observed: dict[Point, dict[str, float]] = {}
    for point, truth in city.ground_truth.items():
        in_corridor = truth["water_level"] > 0.70
        if delay_minutes and in_corridor:
            # 旧观测还没有反映出积涝快速上升。
            rain = truth["rainfall"] * 0.25
            water = truth["water_level"] * 0.20
        else:
            rain = truth["rainfall"]
            water = truth["water_level"]

        uncertainty = min(1.0, 0.08 + delay_minutes / 150.0)
        if delay_minutes and in_corridor:
            uncertainty = min(1.0, uncertainty + 0.15)

        observed[point] = {
            "rainfall": rain,
            "water_level": water,
            "age_minutes": float(delay_minutes),
            "uncertainty": uncertainty,
            # 敏感性代表低洼/监测覆盖/易涝经验等先验信息。
            # 真实系统中可由 DEM、历史积涝点和站点距离计算。
            "sensitivity": 1.0 if in_corridor else 0.02,
        }
    return observed
