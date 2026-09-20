import sys, unittest, tempfile
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from floodroute.dynamic.imerg import import_geotiff

class ImergTests(unittest.TestCase):
    def test_explicit_units_timezone_and_nodata(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as tmp:
            path=Path(tmp)/'synthetic.tif'
            with rasterio.open(path,'w',driver='GTiff',height=1,width=3,count=1,dtype='int16',crs=4326,
                               transform=from_origin(114,23,.1,.1),nodata=-9999) as dst:
                dst.write(np.array([[[10,30,-9999]]],dtype='int16'))
            result=import_geotiff(path,window_end='2023-09-07T12:00:00Z',interval_min=30,scale_to_mm=.1,bbox=(114,22.9,114.3,23))
            self.assertAlmostEqual(result['rain_mm'],2)
            self.assertAlmostEqual(result['valid_fraction'],2/3)
            self.assertEqual(result['timestamp'],'2023-09-07T20:00:00+08:00')
            self.assertEqual(result['spatial_type'],'regional_temporal_forcing')
