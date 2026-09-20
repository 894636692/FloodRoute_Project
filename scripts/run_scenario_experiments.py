from pathlib import Path
import sys, argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from floodroute.runtime import Runtime, default_request, write_json
from floodroute.gis.grid_mapping import grid_polygons, fingerprint
from floodroute.experiments.scenario import generate_truth,save_scenario
from floodroute.experiments.robustness import run_independent

def run(smoke=False):
    runtime=Runtime();cfg=runtime.config
    truth=generate_truth(grid_polygons(ROOT/cfg['grids_path']),cfg)
    save_scenario(truth,cfg,ROOT/'data/scenarios/simulated_extreme')
    # Mid-sequence provides two hours of prehistory and an active moving storm.
    timestamp=sorted(truth.timestamp.unique())[cfg['scenario']['steps']//2].isoformat()
    result=run_independent(runtime,truth,default_request(timestamp),[(30,.2,.1)] if smoke else None)
    out=ROOT/'results/scenario_experiments';out.mkdir(parents=True,exist_ok=True)
    name='smoke' if smoke else 'independent'
    result.to_csv(out/f'{name}.csv',index=False)
    summary=result.groupby(['mode','tau_policy'])[['distance_m','truth_exposure','high_risk_length_ratio','computation_ms']].mean().reset_index()
    write_json(out/f'{name}_summary.json',{'data_type':'SIMULATED_SCENARIO','rows':len(result),'config':cfg,
        'summary':summary.to_dict('records'),'request':default_request(timestamp).__dict__,
        'input_sha256':{cfg[k]:fingerprint(ROOT/cfg[k]) for k in ['static_path','grids_path','mapping_path']},
        'interpretation':'Paired scenario comparisons; one deterministic seed and OD, not independent empirical flood events. One active source: tau comparison tests 45 vs 60 minutes only.'})
    print(summary.to_string(index=False))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--smoke',action='store_true')
    run(parser.parse_args().smoke)
