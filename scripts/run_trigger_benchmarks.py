"""Replay frozen T1/T2 parameters. Does not select or change any parameters."""
from pathlib import Path
import sys
import json
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from floodroute.runtime import Runtime, write_json
from floodroute.common.schema import RouteRequest
from floodroute.gis.grid_mapping import grid_polygons
from floodroute.experiments.benchmarks import benchmark_truth, benchmark_run
from floodroute.experiments.v2 import benchmark_summary

if __name__ == '__main__':
    directory = ROOT/'results/experiment_v2'
    protocol = json.loads((directory/'protocol.json').read_text(encoding='utf-8'))
    config = json.loads((ROOT/'config/selected_v1_1.json').read_text(encoding='utf-8'))
    runtime = Runtime(config); grids = grid_polygons(ROOT/config['grids_path'])
    request = RouteRequest(*protocol['ods'][0], config['scenario']['start'], 'trusted')
    results = []
    for seed in protocol['split']['test']:
        for name in ('T1', 'T2'):
            truth = benchmark_truth(grids, config, protocol['benchmark_centre_utm'], name, seed, protocol['benchmark_width_m'])
            truth.to_parquet(directory/f'{name}_{seed}_truth.parquet', index=False)
            rows = benchmark_run(runtime, truth, request)
            rows.to_csv(directory/f'{name}_{seed}_replay.csv', index=False)
            summary = benchmark_summary(rows);summary['benchmark'] = name;summary['seed'] = seed
            results.append(summary)
    pd.concat(results, ignore_index=True).to_csv(directory/'benchmark_summary.csv', index=False)
    print('Frozen benchmark replay completed; no parameter selection performed.')
