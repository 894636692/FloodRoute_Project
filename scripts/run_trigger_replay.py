from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from floodroute.runtime import Runtime,default_request,write_json
from floodroute.gis.grid_mapping import grid_polygons
from floodroute.experiments.scenario import generate_truth
from floodroute.experiments.replay import run_replay

def run():
    runtime=Runtime();cfg=runtime.config
    truth=generate_truth(grid_polygons(ROOT/cfg['grids_path']),cfg)
    rows=run_replay(runtime,truth,default_request(truth.timestamp.min().isoformat()))
    out=ROOT/'results/trigger_replay';out.mkdir(parents=True,exist_ok=True)
    rows.to_csv(out/'replay.csv',index=False)
    summary=rows.groupby('policy').agg(replan_count=('replan_count','max'),route_change_count=('route_change_count','max'),
        planner_calls=('planner_calls','max'),truth_exposure=('truth_exposure','mean'),distance_m=('distance_m','mean'),computation_ms=('computation_ms','sum')).reset_index()
    write_json(out/'summary.json',{'data_type':'SIMULATED_SCENARIO','config':cfg,'observed':{'delay_min':30,'missing':.2,'noise':.1},
        'summary':summary.to_dict('records'),'metric_note':'Fixed OD repeated decisions, not vehicle movement. Exposure is mean of length-weighted snapshot exposures. Counts exclude initial plan.'})
    print(summary.to_string(index=False))
    return rows

if __name__=='__main__':run()
