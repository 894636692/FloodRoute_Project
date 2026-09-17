# 涝途智避数据验收目录

生成时间：2026-09-17

本目录用于执行项目规划中的第一步：下载并验收基础数据样例。当前采用深圳中心城区样例范围进行可用性验证，后续可根据积涝/降雨数据完整度再确定最终 5x5 km 到 10x10 km 研究区。

## 已下载数据

- `data/raw/osm/shenzhen_center_roads_overpass_2026-09-17.json`
  - 来源：OpenStreetMap Overpass API
  - 范围：`22.50,113.88,22.62,114.08`
  - 内容：道路 way、节点、geometry，约 213,980 个 OSM 元素

- `data/raw/worldcover/ESA_WorldCover_10m_2021_v200_N21E111_Map.tif`
- `data/raw/worldcover/ESA_WorldCover_10m_2021_v200_N21E114_Map.tif`
  - 来源：ESA WorldCover 2021 v200 官方 S3
  - 内容：10m 土地覆盖分类，覆盖深圳跨越的 E111/E114 瓦片

- `data/raw/dem/Copernicus_DSM_COG_10_N22_00_E113_00_DEM.tif`
- `data/raw/dem/Copernicus_DSM_COG_10_N22_00_E114_00_DEM.tif`
  - 来源：Microsoft Planetary Computer / Copernicus DEM GLO-30
  - 内容：30m DSM/高程 COG GeoTIFF，覆盖深圳西侧和东侧 1x1 度瓦片

- `data/raw/shenzhen_open_data/*preview*.json`
  - 来源：深圳开放数据平台页面预览接口
  - 内容：积涝水位、测站基本信息、气象格点实况、气象格网信息各 50 条预览样例

- `data/raw/shenzhen_open_data/open_meteo_shenzhen_center_precip_2026-09-17.json`
  - 来源：Open-Meteo Forecast API
  - 内容：深圳中心点近 1 天和未来 2 天逐小时降雨样例
  - 用途：在深圳开放数据 appKey 未就绪前，作为动态降雨链路的临时替代数据

## 需要注意的限制

- 深圳开放数据正式 API 已定位到，但直接调用返回 `{"errorCode":"10001","message":"未经许可的证书"}`，需要登录平台、创建应用、订阅接口并使用有效 appKey。
- `waterlogging_level_29200_01403147_page1_rows100_2026-09-17.json` 和 `weather_grid_29200_00903509_page1_rows100_2026-09-17.json` 是正式 API 的错误返回，不是有效数据。
- 水务测站基本信息公开表只包含 `STTP`、`STNM`、`STCD`，平台说明经纬度坐标属于保密资料，不公开。因此积涝点落图需要另找公开位置源、地理编码站名，或团队手工核验位置。
- 气象格网信息表包含 `X1`、`Y1`、`X2`、`Y2`，可直接生成 WGS84 网格 polygon。

## 数据清单

详细清单见：

- `data_inventory.xlsx`
  - `dataset_inventory`：按数据集记录来源、状态、字段、下一步
  - `local_files`：按本地文件记录大小、记录数、字段预览

## 下一步

1. 将 OSM Overpass JSON 转为 `roads.graphml` 和 `roads.geojson`。
2. 裁剪并拼接 DEM，生成 `dem_clip.tif` 和 `slope.tif`。
3. 裁剪 WorldCover，与 DEM 对齐。
4. 用气象格网信息生成 polygon，并关联 `GRIDID` 与降雨字段。
5. 申请深圳开放数据 appKey，替换预览样例为正式分页下载。
6. 为积涝测站位置建立可复现方案，再进入研究区选择。
