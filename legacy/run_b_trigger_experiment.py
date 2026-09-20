"""Run B-module trigger experiment on the prepared Shenzhen fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from floodroute.common.schema import RouteRequest
from floodroute.experiments.trigger_experiment import run_delay_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run B trigger experiment with prepared dynamic fixtures.")
    parser.add_argument("--request", default="examples/request_trusted.json")
    parser.add_argument("--static", default="tests/fixtures/b_static.gpkg")
    parser.add_argument("--rainfall", default="data/derived/dynamic/rainfall.csv")
    parser.add_argument("--water", default="data/derived/dynamic/water_level.csv")
    parser.add_argument("--output", default="results/b_routing/trigger_experiment.csv")
    args = parser.parse_args()

    request = RouteRequest.from_dict(json.loads(Path(args.request).read_text(encoding="utf-8")))
    # This fixture reuses the same standardized C-output files for each delay bucket.
    # Later, C can provide one rainfall/water CSV pair per simulated delay.
    delays = (0, 15, 30, 60, 120)
    rainfall_by_delay = {delay: args.rainfall for delay in delays}
    water_by_delay = {delay: args.water for delay in delays}
    rows = run_delay_experiment(args.static, request, rainfall_by_delay, water_by_delay, args.output)
    print(f"wrote {args.output}")
    print(f"scenarios={len(rows)} final_replan_count={rows[-1]['replan_count']}")


if __name__ == "__main__":
    main()
