"""UI-only Python timing; never equates server timing with browser/tile latency."""
from pathlib import Path
import sys, json, time, argparse, subprocess
from contextlib import ExitStack
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import geopandas as gpd
import folium
from floodroute import runtime as runtime_module
from floodroute.runtime import Runtime, default_request, write_json
from floodroute.routing.router import RoadNetworkRouter
from floodroute.ui.controller import snap_click

def run(stage):
    timings={};counts={}
    def measured(name, fn):
        def wrapped(*a,**k):
            t=time.perf_counter()
            try:return fn(*a,**k)
            finally:
                timings[name]=timings.get(name,0)+(time.perf_counter()-t)*1000
                counts[name]=counts.get(name,0)+1
        return wrapped
    start=time.perf_counter()
    with ExitStack() as stack:
        stack.enter_context(patch.object(runtime_module,'read_static',measured('read_static_ms',runtime_module.read_static)))
        stack.enter_context(patch.object(RoadNetworkRouter,'_build_base_graph',measured('build_graph_ms',RoadNetworkRouter._build_base_graph)))
        index_getter=gpd.GeoDataFrame.sindex.fget
        stack.enter_context(patch.object(gpd.GeoDataFrame,'sindex',property(measured('spatial_index_ms',index_getter))))
        if stage=='before':r=Runtime(json.loads((ROOT/'config/selected_v1_1.json').read_text()))
        else:
            from floodroute.ui.resources import load_runtime
            load_runtime.clear();r=load_runtime()
        cold=(time.perf_counter()-start)*1000
        if stage=='after':
            for _ in range(3):assert load_runtime() is r
    from floodroute.ui.observations import get_observations,scenario_times
    start=time.perf_counter();times=scenario_times('REAL');observed=get_observations('REAL',times[-1]);dynamic=(time.perf_counter()-start)*1000
    request=default_request(times[-1]);points={}
    for key,lon,lat in [('start',request.start_lon,request.start_lat),('goal',request.goal_lon,request.goal_lat)]:
        node=r.router.nodes[r.router.nodes.osmid.eq(r.router.nearest_node(lon,lat))].to_crs(4326).geometry.iloc[0]
        start=time.perf_counter();points[key]=snap_click(r.router,node.x,node.y,500)
        timings[key+'_snap_ms']=(time.perf_counter()-start)*1000
    start=time.perf_counter();state=r.observed_state(observed,times[-1]);risk_ms=(time.perf_counter()-start)*1000
    start=time.perf_counter();route=r.plan(state,request);routing_ms=(time.perf_counter()-start)*1000
    cfg=json.loads((ROOT/'config/ui_v1_1.json').read_text())
    start=time.perf_counter()
    if stage=='before':roads=json.loads(r.router.edges[['geometry']].to_crs(4326).to_json())
    else:
        from floodroute.ui.resources import display_roads
        roads=display_roads()
    geojson_ms=(time.perf_counter()-start)*1000
    phases={};payload={}
    from floodroute.ui.map_view import build_map, overlays, MAP_KEY
    import streamlit_folium as sf
    # Freeze the actual pre-change presentation, so --stage before remains
    # reproducible after this UI change without checking out/altering the tree.
    if stage=='before':
        old = subprocess.run(['git','show','e8efc43:src/floodroute/ui/map_view.py'],
                             cwd=ROOT,check=True,capture_output=True,encoding='utf-8').stdout
        namespace={};exec(compile(old,'baseline_map_view.py','exec'),namespace)
        build_map=namespace['build_map']
    components={}
    for mode in ['offline','online']:
        for event in ['cold_start','warm_rerun','start_click','goal_click','route_plan']:
            selection={} if event in ['cold_start','warm_rerun'] else {'start':points['start']} if event=='start_click' else points
            response=route.to_response() if event=='route_plan' else None
            subtimes={}
            def timed(name,fn):
                def wrap(*a,**k):
                    t=time.perf_counter();res=fn(*a,**k);subtimes[name]=subtimes.get(name,0)+(time.perf_counter()-t)*1000;return res
                return wrap
            original_geojson=folium.GeoJson
            def geojson(*a,**k):
                name='route_layer_ms' if k.get('name')=='当前路线' else 'road_layer_ms'
                return timed(name,original_geojson)(*a,**k)
            with patch.object(folium,'Map',timed('create_map_ms',folium.Map)), patch.object(folium,'TileLayer',timed('tile_layer_ms',folium.TileLayer)), patch.object(folium,'GeoJson',geojson), patch.object(folium,'CircleMarker',timed('markers_ms',folium.CircleMarker)):
                start=time.perf_counter();m=build_map(roads,selection,response,mode=='online',cfg)
                construct=(time.perf_counter()-start)*1000
            start=time.perf_counter();html=m.get_root().render();render=(time.perf_counter()-start)*1000
            snap=timings.get(event.replace('_click','_snap_ms'),0)
            phases[mode+'_'+event]={'map_construct_ms':construct,'html_generation_ms':render,'snap_ms':snap,
                'python_total_ms':construct+render+snap+(risk_ms+routing_ms if event=='route_plan' else 0),**subtimes}
            payload[mode+'_'+event]=len(html.encode())
            start=time.perf_counter()
            # Exercise real component serialization, replacing only the browser
            # transport. This is NOT a measurement of browser rendering latency.
            if stage=='after':
                base=build_map(roads,{},None,mode=='online',cfg)
                group=overlays(selection,response,1 if response else None)
            else:
                base=build_map(roads,selection,response,mode=='online',cfg);group=None
            with patch.object(sf,'_component_func',return_value={}) as transport:
                sf.st_folium(base,key=MAP_KEY if stage=='after' else event,feature_group_to_add=group,
                             returned_objects=['last_clicked','bounds','zoom'],height=560)
            args=transport.call_args.kwargs
            serialize_ms=(time.perf_counter()-start)*1000
            base_bytes=sum(len(args.get(k,'').encode()) for k in ('script','header','html'))
            overlay_bytes=len((args.get('feature_group') or '').encode())
            components[mode+'_'+event]={'map_and_component_serialization_ms':serialize_ms,
                'base_payload_bytes':base_bytes,'overlay_payload_bytes':overlay_bytes,
                'effective_key':args['key'],
                'python_total_ms':serialize_ms+snap+(risk_ms+routing_ms if event=='route_plan' else 0)}
    report={'stage':stage,'measurement':'Python perf_counter; browser paint and network NOT measured',
        'cold_start':{'resources_ms':cold,'dynamic_data_ms':dynamic,'display_geojson_ms':geojson_ms,**timings},
        'phases':phases,'component_transport':components,'baseline_commit':'e8efc43',
        'resource_build_counts':counts,'routing_ms':routing_ms,'risk_state_ms':risk_ms,
        'routing_edges':len(r.router.edges),'display_features':len(roads['features']),
        'display_geojson_bytes':len(json.dumps(roads).encode()),'html_bytes':payload,
        'external_tile_latency_ms':None,'browser_first_structure_ms':None,'browser_interactive_ms':None,
        'notes':'Cold resource timings include nested stages; do not sum overlapping timers. Warm cases reuse resources.'}
    write_json(ROOT/f'results/ui_performance_{stage}.json',report)
    print(json.dumps(report,ensure_ascii=True,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['before','after'],required=True)
    run(parser.parse_args().stage)
