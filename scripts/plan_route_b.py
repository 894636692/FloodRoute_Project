"""CLI wrapper for B -> C route planning interface."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from floodroute.routing.service import plan_from_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan route using B routing service.")
    parser.add_argument("--request", default="examples/request_trusted.json")
    parser.add_argument("--static", default="data/derived/static/road_static_features.gpkg")
    parser.add_argument("--rainfall", default="data/derived/dynamic/rainfall.csv")
    parser.add_argument("--water", default="data/derived/dynamic/water_level.csv")
    parser.add_argument("--output", default="results/b_routing/route_result.json")
    args = parser.parse_args()

    response = plan_from_files(
        args.request,
        args.static,
        args.output,
        rainfall_csv=args.rainfall,
        water_level_csv=args.water,
    )
    print(f"wrote {args.output}")
    print(f"distance_m={response['distance_m']} confidence={response['confidence']} mean_risk={response['mean_risk']}")


if __name__ == "__main__":
    main()

