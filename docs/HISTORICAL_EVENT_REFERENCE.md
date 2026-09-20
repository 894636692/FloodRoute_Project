# Historical event reference and optional regional forcing

The Shenzhen Meteorological Bureau documents the extreme rain of **2023-09-07/08**:
[official event report](https://weather.sz.gov.cn/xingxigongkai/gongzuodongtai/content/post_10827001.html).
This motivates a stress scenario; our generated values are NOT observations of that event.

[NASA IMERG documentation](https://gpm.nasa.gov/data/imerg) describes satellite precipitation,
half-hour products and different accumulation/rate units. Coarse regional estimates must not
be interpreted as street-level truth. Final Run includes retrospective processing and cannot
be treated as contemporaneously available planner input without an availability model.

Status: OPTIONAL_EXTERNAL; no IMERG sample or credentials available. Core experiments do not
depend on it. No download/authentication is attempted automatically.

`floodroute.dynamic.imerg.import_geotiff` accepts a locally obtained geographic accumulation
GeoTIFF, explicit timezone-aware window end, duration, documented raw-to-mm scale, and WGS84
regional bounds. For NASA's scaled half-hour accumulation TIFF, verify product metadata before
supplying 30 minutes and 0.1 mm/raw unit. Rate, HDF5 and NetCDF formats are not silently accepted.
Nodata and negative values are excluded from the regional mean and reported through valid_fraction;
the original file is never modified. The importer is tested with synthetic rasters only.

Obtain any restricted product through your own authorized Earthdata/PPS account. Never put keys
or passwords in config. Preserve downloaded files in `data/raw/dynamic/rainfall/imerg/` and record
product version and retrieval time before using this optional regional time series.
