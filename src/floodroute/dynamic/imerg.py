"""Optional local IMERG GeoTIFF regional forcing importer (not street-level truth)."""
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import from_bounds, Window
from floodroute.common.schema import parse_iso8601


def import_geotiff(path, *, window_end, interval_min, scale_to_mm, bbox):
    """Explicit product metadata is mandatory; no filename/unit/time guessing.

    Supports accumulation GeoTIFFs only. scale_to_mm converts stored accumulation
    to mm, not mm/hour. bbox=(west,south,east,north), EPSG:4326.
    Return one regional mean accumulation, validity fraction, and provenance.
    """
    end=parse_iso8601(window_end)
    if interval_min<=0 or scale_to_mm<=0: raise ValueError('Invalid interval/scale')
    with rasterio.open(path) as raster:
        if raster.crs.to_epsg()!=4326: raise ValueError('Requires geographic IMERG GeoTIFF')
        window=from_bounds(*bbox,transform=raster.transform).round_offsets().round_lengths()
        window=window.intersection(Window(0,0,raster.width,raster.height))
        array=raster.read(1,window=window,masked=True).astype(float)
        valid=~np.ma.getmaskarray(array)&np.isfinite(array.data)&(array.data>=0)
        if not valid.any(): raise ValueError('No valid regional pixels')
        transform=raster.window_transform(window)
        lat=transform.f+(np.arange(array.shape[0])+.5)*transform.e
        weights=np.broadcast_to(np.cos(np.radians(lat))[:,None],array.shape)
        mean=float(np.average(array.data[valid]*scale_to_mm,weights=weights[valid]))
    t=pd.Timestamp(end).tz_convert('Asia/Shanghai')
    return {'timestamp':t.isoformat(),'window_start':(t-pd.Timedelta(minutes=interval_min)).isoformat(),
            'rain_mm':mean,'interval_min':interval_min,'valid_fraction':float(valid.mean()),
            'source':'NASA IMERG','spatial_type':'regional_temporal_forcing',
            'data_type':'OPTIONAL_EXTERNAL','scale_to_mm':scale_to_mm,'filename':Path(path).name}
