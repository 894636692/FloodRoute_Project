QGIS 可直接打开的主要成果文件：

1. 推荐打开这个文件：
   D:\LaotuZhBi\laotu-data\data\processed\geopackage\laotu_processed_layers.gpkg

   里面包含图层：
   - roads：OSM 道路，LineString，共 30100 条
   - weather_grid_info_polygons：深圳气象格网范围，Polygon
   - weather_grid_info_centroids：深圳气象格网中心点，Point
   - weather_grid_observation_centroids：气象实况观测中心点，Point
   - weather_grid_observation_polygons：气象实况观测格网面，Polygon
   - open_meteo_current_point：Open-Meteo 当前天气点，Point
   - open_meteo_hourly_precip_points：Open-Meteo 逐小时降雨点，Point

2. 也可以单独打开 GeoJSON：
   D:\LaotuZhBi\laotu-data\data\processed\osm\roads.geojson
   D:\LaotuZhBi\laotu-data\data\processed\shenzhen_open_data\*.geojson

3. CSV 文件只能作为表格打开：
   - station_basic_preview.csv：水务测站基本信息，公开数据不含经纬度，不能直接落图
   - waterlogging_level_preview.csv：积涝点水位预览，只有测站编码/时间/水位，不能直接落图
   - weather_grid_preview.csv：气象格点实况表
   - open_meteo_hourly_precip.csv：逐小时降雨表

4. *_ERROR_NOT_DATA.txt 是正式 API 未授权错误返回，不是有效数据。需要申请深圳开放数据 appKey 后重新下载正式数据。
