"""项目参数。
统一放参数，比如网格大小、起终点、风险权重、Freshness 时间尺度、触发重规划阈值。
先把参数集中放在这里，后续接入真实城市数据时只需要修改配置，
不必在算法代码里到处寻找魔法数字。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # 演示用网格大小。接入真实 OSM 路网后，这两个参数不再参与建图。
    width: int = 15
    height: int = 15
    random_seed: int = 7

    # 可信路线成本中的权重。
    risk_weight: float = 4.0
    uncertainty_weight: float = 1.5
    stale_weight: float = 2.0

    # 静态风险和动态风险的权重。
    elevation_weight: float = 0.35
    slope_weight: float = 0.15
    landcover_weight: float = 0.10
    rain_weight: float = 0.20
    water_weight: float = 0.20

    # 不同动态数据源的有效时间尺度，单位：分钟。
    rain_tau: float = 45.0
    water_tau: float = 20.0

    # 触发式重规划阈值。
    min_route_confidence: float = 0.55
    high_risk_threshold: float = 0.80

    @property
    def start(self) -> tuple[int, int]:
        return (0, self.height // 2)

    @property
    def goal(self) -> tuple[int, int]:
        return (self.width - 1, self.height // 2)
