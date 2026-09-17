"""涝途智避：可运行的最小闭环演示。
主入口。运行它会完成全部流程：生成数据、规划路线、触发判断、输出 CSV/JSON/图片

"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from config import Config
from data import (
    CityData,
    build_demo_city,
    load_city_from_csv,
    load_observed_from_csv,
    make_observed_data,
)
from model import (
    ascii_map,
    calculate_scores,
    city_height,
    city_width,
    plan_route,
    route_metrics,
    should_replan,
)


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_point(value: str) -> tuple[int, int]:
    try:
        x, y = value.split(",", 1)
        return (int(x), int(y))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("坐标格式应为 x,y，例如 0,7") from exc


def run_once(
    delay_minutes: int,
    config: Config,
    city: CityData,
    observed: dict[tuple[int, int], dict[str, float]],
    start: tuple[int, int],
    goal: tuple[int, int],
) -> dict:
    ground_truth = make_observed_data(city, 0)
    observed_scores = calculate_scores(city, observed, config)
    truth_scores = calculate_scores(city, ground_truth, config)

    shortest = plan_route(
        city, start, goal, observed_scores, "shortest", config
    )
    risk = plan_route(city, start, goal, observed_scores, "risk", config)
    trusted = plan_route(
        city, start, goal, observed_scores, "trusted", config
    )
    trigger, reason, confidence = should_replan(risk, observed_scores, config)
    recommended = trusted if trigger else risk

    return {
        "delay_minutes": delay_minutes,
        "trigger_replan": trigger,
        "trigger_reason": reason,
        "route_confidence": round(confidence, 4),
        "routes": {
            "shortest": shortest,
            "risk": risk,
            "trusted": trusted,
            "recommended": recommended,
        },
        "metrics": {
            "shortest": route_metrics(shortest, observed_scores, truth_scores),
            "risk": route_metrics(risk, observed_scores, truth_scores),
            "trusted": route_metrics(trusted, observed_scores, truth_scores),
            "recommended": route_metrics(recommended, observed_scores, truth_scores),
        },
    }


def write_summary(all_results: list[dict]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for result in all_results:
        for route_name, metrics in result["metrics"].items():
            rows.append(
                {
                    "delay_minutes": result["delay_minutes"],
                    "route": route_name,
                    "trigger_replan": result["trigger_replan"],
                    **metrics,
                }
            )

    with (RESULTS_DIR / "summary.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def plot_routes(
    result: dict,
    config: Config,
    city: CityData,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> Path:
    """保存一张路线对比图，便于汇报和调参。"""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    truth = make_observed_data(city, 0)
    truth_scores = calculate_scores(city, truth, config)

    risk_grid = np.zeros((city_height(city), city_width(city)))
    for x, y in city.nodes:
        risk_grid[y, x] = truth_scores[(x, y)]["risk"]

    fig, ax = plt.subplots(figsize=(8, 7), dpi=140)
    image = ax.imshow(risk_grid, origin="lower", cmap="YlOrRd", vmin=0, vmax=1)
    fig.colorbar(image, ax=ax, label="Ground Truth risk")

    styles = {
        "shortest": ("#333333", "--", "Shortest"),
        "risk": ("#2374ab", "-", "Risk route"),
        "trusted": ("#008f5a", "-", "Trusted route"),
    }
    for name, (color, linestyle, label) in styles.items():
        route = result["routes"][name]
        xs = [point[0] for point in route]
        ys = [point[1] for point in route]
        ax.plot(xs, ys, color=color, linestyle=linestyle, linewidth=2.5, label=label)

    ax.scatter(*start, marker="o", s=90, c="#111111", label="Start")
    ax.scatter(*goal, marker="*", s=140, c="#111111", label="Goal")
    ax.set_title(f"Route comparison, delay={result['delay_minutes']} min")
    ax.set_xticks(range(config.width))
    ax.set_yticks(range(config.height))
    ax.grid(color="white", linewidth=0.5, alpha=0.45)
    ax.legend(loc="upper right")
    ax.set_aspect("equal")

    path = RESULTS_DIR / f"routes_delay_{result['delay_minutes']}min.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="涝途智避 MVP")
    parser.add_argument("--data", choices=["demo", "csv"], default="demo")
    parser.add_argument("--nodes", default="data/real/nodes.csv")
    parser.add_argument("--edges", default="data/real/edges.csv")
    parser.add_argument("--observed", default="data/real/observed.csv")
    parser.add_argument("--start", type=parse_point)
    parser.add_argument("--goal", type=parse_point)
    parser.add_argument("--delay", type=int, default=120)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    config = Config()
    start = args.start or config.start
    goal = args.goal or config.goal

    if args.data == "csv":
        city = load_city_from_csv(args.nodes, args.edges)
        observed = load_observed_from_csv(city, args.observed, args.delay)
        all_results = [run_once(args.delay, config, city, observed, start, goal)]
    else:
        city = build_demo_city(config.width, config.height, config.random_seed)
        delays = [0, 15, 30, 60, 120]
        all_results = [
            run_once(
                delay,
                config,
                city,
                make_observed_data(city, delay),
                start,
                goal,
            )
            for delay in delays
        ]

    save_json(RESULTS_DIR / "routes.json", all_results)
    write_summary(all_results)

    latest = all_results[-1]
    plot_path = plot_routes(latest, config, city, start, goal)
    print("涝途智避 MVP 已运行")
    print(f"起点: {start}  终点: {goal}")
    print(f"{latest['delay_minutes']} 分钟延迟场景: {latest['trigger_reason']}")
    print(f"路线可信度: {latest['route_confidence']}")
    print("\n路线图: A=起点, B=终点, S=最短路, R=风险路, T=可信路")
    print(
        ascii_map(
            city,
            {
                "shortest": latest["routes"]["shortest"],
                "risk": latest["routes"]["risk"],
                "trusted": latest["routes"]["trusted"],
            },
            start,
            goal,
        )
    )
    print(f"\n结果文件已写入: {RESULTS_DIR}")
    print("  - routes.json：每个延迟场景的路线和重规划决策")
    print("  - summary.csv：真实风险、绕行长度、高风险路段等指标")
    print(f"  - {plot_path.name}：120分钟延迟场景的路线对比图")


if __name__ == "__main__":
    main()
