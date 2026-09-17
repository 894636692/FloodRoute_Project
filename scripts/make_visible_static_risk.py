from pathlib import Path
import json
import numpy as np
from osgeo import gdal

root = Path(r'D:\LaotuZhBi\laotu-data')
static = root / 'data' / 'processed' / 'static_risk'
risk_path = static / 'static_risk.tif'
out_rgb = static / 'static_risk_rgb_visible.tif'
bbox_geojson = static / 'study_area_bbox.geojson'

ds = gdal.Open(str(risk_path))
if ds is None:
    raise RuntimeError(f'Cannot open {risk_path}')
arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
nodata = ds.GetRasterBand(1).GetNoDataValue()
valid = np.isfinite(arr) & (arr != nodata)
arr2 = np.clip(arr, 0, 1)
r = np.zeros(arr.shape, dtype=np.uint8)
g = np.zeros(arr.shape, dtype=np.uint8)
b = np.zeros(arr.shape, dtype=np.uint8)
low = arr2 <= 0.5
high = arr2 > 0.5
r[low] = (26 + (255 - 26) * (arr2[low] / 0.5)).astype(np.uint8)
g[low] = (152 + (255 - 152) * (arr2[low] / 0.5)).astype(np.uint8)
b[low] = (80 + (191 - 80) * (arr2[low] / 0.5)).astype(np.uint8)
r[high] = (255 + (215 - 255) * ((arr2[high] - 0.5) / 0.5)).astype(np.uint8)
g[high] = (255 + (48 - 255) * ((arr2[high] - 0.5) / 0.5)).astype(np.uint8)
b[high] = (191 + (39 - 191) * ((arr2[high] - 0.5) / 0.5)).astype(np.uint8)
r[~valid] = 0
g[~valid] = 0
b[~valid] = 0

driver = gdal.GetDriverByName('GTiff')
out = driver.Create(str(out_rgb), ds.RasterXSize, ds.RasterYSize, 3, gdal.GDT_Byte, options=['COMPRESS=LZW', 'TILED=YES'])
out.SetGeoTransform(ds.GetGeoTransform())
out.SetProjection(ds.GetProjection())
for i, band_arr in enumerate([r, g, b], start=1):
    band = out.GetRasterBand(i)
    band.WriteArray(band_arr)
    band.SetNoDataValue(0)
out.FlushCache()
out = None
ds = None

bbox = [113.88, 22.50, 114.08, 22.62]
poly = [[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]], [bbox[0], bbox[1]]]
fc = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [poly]}, 'properties': {'name': 'static risk study area', 'bbox': '113.88,22.50,114.08,22.62'}}]}
bbox_geojson.write_text(json.dumps(fc, ensure_ascii=False), encoding='utf-8')
print(out_rgb)
print(bbox_geojson)
