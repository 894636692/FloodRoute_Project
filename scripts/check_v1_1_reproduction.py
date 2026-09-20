"""Compare an independently rerun v2 folder, excluding measured wall-clock time."""
from pathlib import Path
import json
import sys
import subprocess
import hashlib
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from floodroute.runtime import write_json

if __name__ == '__main__':
    original = ROOT/'results/experiment_v2'
    repeated = ROOT/'work/experiment_v2_reproduction'
    checked = []
    for path in sorted(original.glob('*.csv')):
        counterpart = repeated/path.name
        if not counterpart.exists(): raise ValueError('Missing reproduction file: '+path.name)
        a, b = pd.read_csv(path), pd.read_csv(counterpart)
        timed = [c for c in a if c.endswith('_ms')]
        pd.testing.assert_frame_equal(a.drop(columns=timed), b.drop(columns=timed), check_exact=False, rtol=1e-12, atol=1e-12)
        checked.append(path.name)
    for name in ['parameter_selection.json','scenario_split.json','protocol.json','run_manifest.json']:
        a = json.loads((original/name).read_text(encoding='utf-8'))
        b = json.loads((repeated/name).read_text(encoding='utf-8'))
        if a != b: raise ValueError('Reproduction mismatch: '+name)
        checked.append(name)
    for path in original.glob('*_truth.parquet'):
        pd.testing.assert_frame_equal(pd.read_parquet(path),pd.read_parquet(repeated/path.name))
        checked.append(path.name)
    protected = ['data','src/floodroute/gis','src/floodroute/dynamic','src/floodroute/risk',
                 'src/floodroute/routing','src/floodroute/runtime.py','config/final_v1.json']
    subprocess.run(['git','diff','--exit-code','v1.0-engineering','--',*protected],cwd=ROOT,check=True,capture_output=True)
    ref = subprocess.check_output(['git','rev-parse','v1.0-engineering'],cwd=ROOT,text=True).strip()
    branch = subprocess.check_output(['git','rev-parse','integration/final-v1'],cwd=ROOT,text=True).strip()
    if ref != branch: raise ValueError('Stable branch moved')
    digests = {}
    for name in ['data/derived/static/road_static_features.gpkg','data/derived/dynamic/shenzhen_grid/rainfall.csv',
                 'data/derived/dynamic/shenzhen_grid/grid_cells.csv']:
        digests[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    write_json(original/'reproducibility.json',{'independent_complete_runs':2,'passed':True,
        'checked_files':checked,'excluded_columns':'columns ending in _ms only',
        'numeric_tolerance':1e-12,'selection_identical':True,'stable_ref':ref,
        'protected_paths_unchanged':protected,'input_sha256':digests})
    print('Reproduction passed:',len(checked),'files; protected data/code and stable branch unchanged.')
