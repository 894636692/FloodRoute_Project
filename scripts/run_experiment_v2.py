"""Reproduce parameter selection, held-out comparisons and T1/T2 benchmarks."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from floodroute.runtime import Runtime
from floodroute.gis.grid_mapping import grid_polygons
from floodroute.experiments.v2 import run_v2

if __name__ == '__main__':
    runtime = Runtime()
    run_v2(runtime, grid_polygons(ROOT/runtime.config['grids_path']), ROOT/'results/experiment_v2')
