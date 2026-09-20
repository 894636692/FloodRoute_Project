"""Build a small UI background. NEVER consumed by routing or risk calculation."""
from pathlib import Path
import sys, json, hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import geopandas as gpd
import shapely
from floodroute.ui.resources import load_runtime
from floodroute.runtime import write_json

if __name__=='__main__':
    r=load_runtime()
    major=r.router.edges[r.router.edges.highway.isin(['motorway','trunk','primary','secondary','tertiary','residential'])]
    geometry=shapely.line_merge(shapely.union_all(major.geometry)).simplify(15, preserve_topology=True)
    geographic=gpd.GeoSeries([geometry],crs=32650).to_crs(4326).iloc[0]
    def rounded(obj):
        if isinstance(obj,(list,tuple)):return [rounded(v) for v in obj]
        if isinstance(obj,float):return round(obj,6)
        return obj
    geom=shapely.geometry.mapping(geographic);geom['coordinates']=rounded(geom['coordinates'])
    result={'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':geom}]}
    out=ROOT/'data/derived/display';out.mkdir(parents=True,exist_ok=True)
    (out/'roads_display.geojson').write_text(json.dumps(result,separators=(',',':')),encoding='utf-8')
    write_json(out/'manifest.json',{'use':'display only; never routing','source_edges':len(r.router.edges),
        'selected_edges':len(major),'display_features':1,'simplification_m':15,'coordinate_decimals':6,
        'omitted_for_display':'service/link/other minor road classes; opposite directions visually merged',
        'source_sha256':hashlib.sha256((ROOT/r.config['static_path']).read_bytes()).hexdigest(),
        'display_bytes':(out/'roads_display.geojson').stat().st_size})
