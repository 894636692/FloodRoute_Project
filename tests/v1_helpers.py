"""Small explicitly synthetic network for executable integration tests."""
import copy
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString,box
from floodroute.runtime import Runtime,load_config
from floodroute.routing.router import RoadNetworkRouter
from floodroute.risk.trusted import RiskEngine
from floodroute.common.schema import RouteRequest
from floodroute.experiments.scenario import generate_truth


def mini_runtime():
    rows=[]
    points={y*4+x:(200000+x*100,2490000+y*100) for x in range(4) for y in range(4)}
    for u,xy in points.items():
        for v in [u+1 if u%4<3 else -1,u+4]:
            if v not in points:continue
            for a,b in [(u,v),(v,u)]:
                rows.append(dict(u=a,v=b,key=0,length_m=100.,geometry=LineString([points[a],points[b]]),
                    low_elev_norm=(u%4)/4,flatness_risk=.8,builtup_frac=.8,vegetation_frac=.2,water_frac=0.,
                    elev_mean_m=10.,elev_min_m=9.,slope_mean_deg=3.,source_version='SYNTHETIC_TEST',
                    dem_valid_frac=1.,slope_valid_frac=1.,worldcover_valid_frac=1.,quality_flag='ok'))
    r=Runtime.__new__(Runtime);r.config=copy.deepcopy(load_config());r.edges=gpd.GeoDataFrame(rows,crs=32650)
    r.weights=r.edges[['u','v','key']].copy();r.weights['grid_id']=(r.weights.u%4).astype(str);r.weights['weight']=1.
    r.coverage=r.edges[['u','v','key']].copy();r.coverage['coverage_fraction']=1.
    r.engine=RiskEngine(r.edges,r.config);r.router=RoadNetworkRouter(r.edges)
    grids=gpd.GeoDataFrame({'grid_id':['0','1','2','3']},geometry=[box(i,i,i+1,i+1) for i in range(4)],crs=32650)
    truth=generate_truth(grids,r.config)
    ends=gpd.GeoSeries.from_xy([points[0][0],points[15][0]],[points[0][1],points[15][1]],crs=32650).to_crs(4326)
    request=RouteRequest(ends[0].x,ends[0].y,ends[1].x,ends[1].y,truth.timestamp.max().isoformat(),'trusted')
    return r,truth,request
