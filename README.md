# 涝途智避 MVP

面向异步多源信息可信度的城市内涝触发式应急路径规划系统。

## C 组真实动态数据进度（2026-09-18）

真实深圳站点名录和水位样本已取得并生成可复现中间表；NOAA 宝安站历史降雨候选已解析。水务站点坐标及水位时间/测量定义仍待确认；根目录的派生水位、降雨 CSV 继续是 fixture 联调样例。

深圳实况格点两表已归档：100,000 条记录全部匹配 4,232 个唯一格网，WGS84 已由官方页面确认，时间定义已由用户补充，见[下载验收](docs/shenzhen_rainfall_download_check_2026-09-18.md)。

随后已按用户确认的时间定义生成[真实格网降雨候选接口](docs/shenzhen_rainfall_candidate.md)，独立保存在 `data/derived/dynamic/shenzhen_grid/`。候选可直接用 pandas 读取；获取时刻缺失及 B 的格网/质量状态处理仍需验收，尚未切换默认模拟输入。

运行命令、数据边界与交接要求见 [C 动态数据运行说明](docs/c_dynamic_runbook.md)，逐数据集状态见 [动态数据清单](docs/dynamic_data_inventory.csv)。

仓库包含可直接读取的真实降雨候选 CSV、代码、测试和验收报告；原始下载包、中间大表及截图证据保留本地，不随 Git 同步。队友复现清洗前需取得对应原件，读取已生成候选 CSV 则无需原件。

## 运行

推荐使用 Anaconda 环境：

```powershell
conda env create -f environment.yml
conda activate flood-route-mvp
```

如果直接使用当前 Anaconda base 环境，也可以安装最少依赖：

```powershell
pip install -r requirements.txt
```

运行主程序：

```powershell
python main.py
```

运行后会在 `results/` 生成：

- `routes.json`：不同数据延迟下的路线、可信度和重规划结果
- `summary.csv`：路线长度、真实风险、高风险节点数量等实验指标
- `routes_delay_120min.png`：120 分钟延迟场景下的路线对比图

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 文件关系

```text
main.py
  -> data.py       生成/读取数据
  -> model.py      风险计算、路径规划、触发判断、指标
  -> config.py     参数和权重
  -> results/      输出结果
```

## 当前数据说明

当前 `data.py` 生成一个 15×15 的示例城市网格，并模拟一条横穿起点和终点的高风险积涝走廊。延迟场景会让算法看到该走廊的旧数据，但评价时使用最新的 Ground Truth。代码还给易涝走廊设置了更高的 `sensitivity`，表示低洼、监测覆盖或历史易涝先验会让这类道路更怕旧数据。

因此可以直接观察：

1. 最短路线可能穿过高风险区域。
2. 普通风险路线依赖当前观测值。
3. 可信路线会惩罚过期且不确定的数据。
4. 当当前路线可信度下降时，系统触发重新规划。

## 后续接入真实数据

### 已下载的深圳小范围数据

已准备一个约 5×5 km 的深圳中心城区小范围数据包：

```text
研究区 bbox(WGS84): 114.03,22.50,114.08,22.55
对齐投影: EPSG:32650 / UTM Zone 50N
```

原始数据：

```text
data/raw/copernicus_dem_glo30_N22E114.tif
data/raw/esa_worldcover_2021_N21E114.tif
```

裁剪与对齐结果：

```text
data/processed/shenzhen_core/dem_wgs84_clip.tif
data/processed/shenzhen_core/worldcover_wgs84_clip.tif
data/processed/shenzhen_core/dem_utm_30m.tif
data/processed/shenzhen_core/worldcover_utm_30m_match_dem.tif
data/processed/shenzhen_core/osm_drive.graphml
data/processed/shenzhen_core/osm_nodes_wgs84.geojson
data/processed/shenzhen_core/osm_edges_wgs84.geojson
data/processed/shenzhen_core/osm_nodes_utm.geojson
data/processed/shenzhen_core/osm_edges_utm.geojson
data/processed/shenzhen_core/metadata.json
data/processed/shenzhen_core/shenzhen_data_check.png
```

一键重新下载和处理：

```powershell
python scripts/download_shenzhen_data.py
```

生成叠加检查图：

```powershell
python scripts/plot_shenzhen_data_check.py
```

数据来源：

- Copernicus DEM GLO-30：公开 COG tile `N22E114`
- ESA WorldCover 2021 v200：公开 COG tile `N21E114`
- OpenStreetMap：通过 OSMnx / Overpass API 获取 drive 路网

### 第一阶段：用 CSV 换成真实/半真实数据

现在代码已经支持 CSV 数据模式。你可以先不接复杂 GIS 文件，把真实数据整理成三张表：

```text
data/real/nodes.csv
data/real/edges.csv
data/real/observed.csv
```

`nodes.csv` 表示道路节点及其真实风险背景：

```csv
x,y,low_elevation,slope,landcover,rainfall_truth,water_level_truth
```

`edges.csv` 表示哪些节点之间有道路连接：

```csv
from_x,from_y,to_x,to_y
```

`observed.csv` 表示算法当前能看到的观测数据：

```csv
x,y,rainfall_observed,water_level_observed,age_minutes,uncertainty,sensitivity
```

运行 CSV 模式：

```powershell
python main.py --data csv --start 0,1 --goal 7,1 --delay 120
```

注意：当前所有风险字段都要求提前归一化到 `0~1`。

- `low_elevation`：越低洼越接近 1。
- `slope`：越容易积水越接近 1，第一版可把低坡度设为高风险。
- `landcover`：硬化地面/建设用地较高，绿地较低。
- `rainfall_truth`、`water_level_truth`：最新真实值，用于评价路线。
- `rainfall_observed`、`water_level_observed`：算法当前看到的值，可能是旧值。
- `age_minutes`：观测数据延迟了多久。
- `uncertainty`：不确定性，越不可靠越接近 1。
- `sensitivity`：道路对旧数据的敏感程度，低洼、历史易涝、监测点附近可设高一些。

### 第二阶段：接入 DEM/OSM/降雨/积涝

后续再逐步替换 `data.py` 中的 `build_demo_city()` 和 `make_observed_data()`：

- DEM、坡度、土地覆盖：转换为节点或道路的静态特征
- OSM：替换为真实道路邻接关系
- 降雨、积涝、水位：填入 `observed` 和 `ground_truth`
- `model.py` 的风险和路径逻辑可以保持不变
