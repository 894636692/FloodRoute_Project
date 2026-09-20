from pathlib import Path
import sys, os, json
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from floodroute.gis.io import read_static
from floodroute.gis.grid_mapping import grid_polygons, save_mapping

if __name__ == '__main__':
    os.chdir(ROOT)
    cfg=json.loads((ROOT/'config/final_v1.json').read_text())
    report=save_mapping(read_static(cfg['static_path']), grid_polygons(cfg['grids_path']),
                        cfg['mapping_path'], [cfg['static_path'],cfg['grids_path']])
    print(json.dumps(report, indent=2))
