# 阶段 1：地图数据可行性测试

记录日期：2026-09-17。结论：技术检查及当前地图尺度下的目视叠加检查通过。

本阶段证明 DEM、WorldCover 与 OSM 道路能够获取、读取、裁剪、检查坐标系并在同一位置叠加。没有进行内涝风险计算、路径规划或模型训练。

## 1. 测试区域

深圳福田附近，候选中心为 WGS 84 经度 114.055、纬度 22.545。
在 EPSG:32650（WGS 84 / UTM 50N）下构建 5000 m × 5000 m 正方形，投影平面面积为 25 km²，再转换为 EPSG:4326 保存。

**该区域只是技术测试区，不是最终研究区。** 唯一裁剪边界为根目录的 `study_area.geojson`。

## 2. bbox

| 参数 | 数值（度） |
|---|---:|
| min_lon | 114.0302354682249 |
| min_lat | 22.521998807089567 |
| max_lon | 114.07975666167043 |
| max_lat | 22.567998449216287 |

bbox 是包住测试区的经纬度外包矩形，用于数据请求。它不等于转换后的多边形；最终裁剪使用同一份多边形。

## 3. 数据源

| 数据 | 产品与访问方式 | 本地来源记录 |
|---|---|---|
| DEM | Copernicus GLO-30 Public，AWS 开放 COG；瓦片 N22/E114 | `data/raw/dem/copernicus_glo30_source.json` |
| 土地覆盖 | ESA WorldCover 2021 v200，官方 AWS 开放 COG；瓦片 N21E114 | `data/raw/worldcover/worldcover_2021_v200_source.json` |
| 道路 | OpenStreetMap，经 OSMnx / Overpass 获取，`network_type="drive"` | `data/raw/osm/api_cache/` 中的原始响应 |

- [Copernicus 数据访问与说明](https://copernicus-dem-30m.s3.amazonaws.com/readme.html)
- [Copernicus 产品说明](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM)
- [WorldCover 官方数据说明](https://esa-worldcover.org/en/data-access)
- [WorldCover 2021 v200 DOI](https://doi.org/10.5281/zenodo.7254221)
- [OpenStreetMap 版权与许可](https://www.openstreetmap.org/copyright)

两份栅格仅获取覆盖测试区的原分辨率窗口，保留原像元值及有效性掩膜；`source_window.tif` 是源数据子集，不是完整远程瓦片。原始窗口未被后续处理覆盖。公开读取未使用 API Key。

## 4. CRS 与分辨率

| 数据 | 水平 CRS | 分辨率或数据类型 | 输出数组大小（行 × 列） |
|---|---|---|---|
| DEM | EPSG:4326 | 1 角秒，约 30 m；float32 | 167 × 179 |
| WorldCover | EPSG:4326 | 0.3 角秒，约 10 m；uint8 | 553 × 596 |
| OSM 道路 | EPSG:4326 | 矢量折线，无固定像元分辨率 | 不适用 |

DEM 高程单位为米，垂直参考为 EGM2008。它实际是 DSM，包含建筑和植被影响，不能当作高精度裸地地形模型。

经纬度的单位为度，不直接用于米制距离、缓冲或平方米面积计算。测试区构建进行了 EPSG:4326 → EPSG:32650 → EPSG:4326 转换。三份最终数据 CRS 已一致，无须为本次显示叠加额外重投影。OSMnx 内部为边界处理使用投影和缓冲，输出仍为 EPSG:4326。

## 5. 已完成的处理与检查

1. 创建独立 `.venv`（Windows / Python 3.13.3），依赖版本保存在 `requirements.txt`。
2. 构建和保存唯一测试边界。
3. 下载并简化 OSM 驾车路网，保留所有连通分量；GraphML 保留连接关系，GeoJSON 保存裁剪后的显示线段。
4. 读取栅格局部窗口，在原网格上按多边形裁剪；采用像元中心落入判定，未重采样或合并类别。
5. 逐层检查 CRS、范围、有效像元、道路字段及类别编号。
6. 使用各栅格自己的空间范围和坐标变换绘图；三层图中 WorldCover 透明度为 50%。未人为平移图层。

| 检查项 | 结果 |
|---|---|
| OSM 节点 / 有向边 | 2027 / 3886 |
| 裁剪后道路记录 | 3822 |
| DEM 有效像元 / 区域内缺失 | 28392 / 0 |
| DEM 最低 / 最高 / 中位高程 | 0.362 / 163.265 / 17.133 m |
| WorldCover 有效像元 / 区域内缺失 | 315592 / 0 |
| WorldCover 类别 | 10、30、40、50、60、80、90；无未知编号 |

WorldCover 建成区与树木覆盖分别占有效像元的 55.57% 和 39.08%；这是分类像元占比，不是经过实地验证的精确面积比例。草本湿地仅 1 个像元，不能据此认定真实湿地。

GeoJSON 中 `length_original_m` 表示裁剪前完整道路边长度，不是裁剪片段长度。裁剪后的道路图层不是重新构建的可路由网络。

## 6. 目视验收

已逐张查看 DEM＋道路、WorldCover＋道路和三层叠加 PNG：

- 道路密集区与建成区大致对应。
- 北部大片树木覆盖区内部可驾车道路较少，周边道路位置与覆盖边界大致吻合。
- 两份栅格覆盖同一测试区，没有区域内部缺失像元。
- 在当前地图尺度下未发现明显的全局平移、翻转或整体空间错位。
- DEM 能显示连续的高程变化，未发现明显的 NoData 混入高程统计；没有独立地面高程真值验证。

因此本轮“多源地图数据可行性测试”通过。此结论不等于测绘精度认证，也不证明数据已经适合精细内涝建模。WorldCover 为 2021 年，OSM 为本次获取的数据，局部差异可能包含地物变化、分类误差及分辨率差异。

## 7. 最终输出

地图位于 `outputs/maps/`：

- `osm_roads_test.png`
- `dem_test.png`
- `worldcover_test.png`
- `dem_osm_overlay.png`
- `worldcover_osm_overlay.png`
- `three_layers_overlay.png`

处理数据为 `data/processed/osm/network.graphml`、`data/processed/osm/roads.geojson`、`data/processed/dem/dem_clip.tif`、`data/processed/worldcover/worldcover_clip.tif`。

`outputs/overlay_checks.json` 是脚本生成的技术检查记录，脚本本身始终提示需目视检查；本文件第 6 节记录了本次实际完成的图像检查。重新生成或替换数据后需要重新验收。

## 8. 遇到的问题与解决方式

| 问题或疑问 | 处理 |
|---|---|
| 原有 Python 环境缺少完整 GIS 依赖 | 使用独立 Python 3.13.3 创建项目 `.venv`，安装指定工具及必要依赖；导入和 `pip check` 通过 |
| 两份栅格大小、边界数值不同 | 保持原始网格，按各自地理范围叠图；显示叠加不要求相同数组形状 |
| 多边形裁剪后边缘出现台阶或细白缝 | 属于像元中心判定和完整像元网格的正常表现；区域内部缺失另行检查 |
| WorldCover 图例被截断 | 导出时使用 `bbox_inches="tight"` 和留白，复查后图例完整 |
| 道路类型字段可能含多个值 | 保留多值语义；统计显示时转换为文字，完整图属性保存在 GraphML |

## 9. 重现与文件管理

在项目根目录的 VS Code PowerShell 终端中，用 `.\.venv\Scripts\python.exe` 运行脚本。

```powershell
.\.venv\Scripts\python.exe src\check_environment.py
# study_area.geojson 已存在时跳过 define_study_area.py；脚本禁止覆盖既有边界。
.\.venv\Scripts\python.exe src\download_osm.py
.\.venv\Scripts\python.exe src\download_dem.py
.\.venv\Scripts\python.exe src\download_worldcover.py
.\.venv\Scripts\python.exe src\plot_overlay.py
```

下载脚本优先复用已有缓存或源窗口；处理结果和地图可以重新生成。`raw`、`processed`、`outputs` 分开管理。Git 忽略数据、生成图片、临时文件、虚拟环境和密钥；源代码、边界、依赖清单和本记录可纳入版本控制。本阶段提交包含源代码、测试区边界、依赖清单和本记录；数据与地图需在本地运行脚本生成。

## 10. 下一阶段准备

先由团队复现本轮流程，确认最终研究区及所需数据质量。若后续需要逐像元计算，再明确米制 CRS、共同网格、像元对齐和重采样规则；分类数据不能使用双线性插值。风险模型与路径规划需另行制定方案，本轮未启动。
