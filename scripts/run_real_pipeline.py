from pathlib import Path
import sys, time
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from floodroute.runtime import Runtime, read_rainfall, default_request, route_metrics, write_json
from floodroute.gis.grid_mapping import fingerprint


def run():
    runtime=Runtime(); cfg=runtime.config
    observed=read_rainfall(ROOT/cfg['rainfall_path'])
    timestamp=observed.timestamp.max().tz_convert('Asia/Shanghai').isoformat()
    state=runtime.observed_state(observed,timestamp)
    lengths=runtime.edges.set_index(['u','v','key']).length_m
    out=ROOT/'results/real_pipeline'; metrics={}
    for mode in ['shortest','risk','trusted']:
        begin=time.perf_counter(); route=runtime.plan(state,default_request(timestamp,mode))
        metrics[mode]=route_metrics(route,state,lengths,cfg['routing']['high_risk'])
        metrics[mode]['computation_ms']=(time.perf_counter()-begin)*1000
        response=route.to_response()
        write_json(out/f'real_{mode}.geojson',{'type':'FeatureCollection','features':[{'type':'Feature','geometry':response.pop('geometry_geojson'),'properties':{**response,**metrics[mode],'data_type':'DERIVED_FROM_REAL'}}]})
    write_json(out/'real_pipeline_metrics.json',{'timestamp':timestamp,'routes':metrics,'config':cfg,'rain_mm_min':float(observed.rain_mm.min()),'rain_mm_max':float(observed.rain_mm.max())})
    write_json(out/'data_provenance.json',{'static':'DERIVED_FROM_REAL','rainfall':'REAL','water_source_active':False,
        'time_semantics':'Asia/Shanghai preceding hour ending at FORECASTTIME; user confirmed',
        'retrieved_at':'unknown; snapshot replay demonstrates ingestion, not historical online availability',
        'risk_output':'road flood risk index, not water depth',
        'sha256':{cfg[key]:fingerprint(ROOT/cfg[key]) for key in ['static_path','rainfall_path','grids_path','mapping_path']}})
    print(metrics)
    return metrics

if __name__=='__main__': run()
