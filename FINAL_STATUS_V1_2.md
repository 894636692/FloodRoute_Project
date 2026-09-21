# FloodRoute v1.2 最终状态

日期：2026-09-21。发布分支：`main`；发布标签：`v1.2.0`。

`manual_visual_review = passed`

v1.2 已形成“数据可查看 → 风险可解释 → 路线可规划 → 动态变化可回放”的完整演示链路。Google Chrome 已完成真实用户浏览器核心操作验收；没有单独人工确认的显示器、硬件和浏览器版本组合继续在检查表中保留 pending。

## 发布门禁

- 发布实现提交：`0aa63c824db37deb0f3720f67bdac778d53d5f25`。
- 冻结参数：`config/selected_v1_1.json`，SHA256 `6BF703FB88A01640BE4347A84C8BF608D41F2A55169484DA0ECE6EACC692E4E6`。
- 环境：Windows 11 家庭版中文版 64 位，版本 `10.0.26200`；Python `3.13.3`。
- `python -m pip check`：通过，未发现依赖冲突。
- `python -m unittest discover -s tests -q`：105 项通过，unittest 报告 147.980 秒，发布命令总耗时 152.606 秒。
- CI：`.github/workflows/test.yml` 使用 `windows-latest`、Python 3.13、Git LFS 与 `requirements-lock.txt`，只执行依赖和工程回归测试。

## 保护范围

- 从 `experiment-ui/v1.1` 创建独立分支，没有修改 main、`integration/final-v1` 或 `v1.0-engineering`。
- 正式 GIS、真实 rainfall 原始值、Risk/Routing/Trigger 核心、Ground Truth、Experiment v2 结果和冻结参数未修改。
- 真实水位保持 `water.active=false`；没有伪造坐标、水位、道路积水深度或额外累计降雨窗口。
- 原有未跟踪数据和用户工作文件未加入提交。

## 新增功能

1. **自然道路选点。** WGS84 点击转 EPSG:32650，搜索最近正式候选机动车道路边；marker 放在道路最近点，路由仍用更近的端点节点。端点可选阈值100米，后端安全阈值500米。
2. **无效点击保护。** 超阈值只显示轻量提示，不生成 marker，不覆盖端点，不清除旧结果，不规划，不改变中心/缩放，也不执行 `fitBounds`。
3. **查看信息。** 任意位置可查询最近官方气象格网、当前近1小时雨量、最近正式道路距离、地形、土地覆盖及当前风险组成，不修改起终点或运行规划器。
4. **降雨格网。** 4,232 个官方格网 geometry 在浏览器只加载一次，动态只传 `[grid_id,rain_mm,level]`。只显示数据实际支持的前一小时累计量。
5. **道路风险。** 26,254 条展示用简化道路 geometry 在浏览器只加载一次，动态只传 `[edge_id,risk,level]`；后台正式路由仍使用55,727条完整候选机动车有向边。
6. **道路解释。** 点击风险道路可返回该正式道路边的长度、可靠名称/类型、地形、土地覆盖、降雨与风险组成；缺失值显示“暂无可靠数据”。
7. **真实水位说明。** UI 明确显示“真实水位数据：未启用”及坐标、时间语义、测量基准三项原因。
8. **导出。** GeoJSON 包含场景、时间、中文策略、起终点、路线ID、距离、风险暴露、可信度、新鲜度、不确定性、预计时间、Trigger状态和数据来源，不含 Ground Truth。

## 实现方式

地图入口仍为 `src/floodroute/ui/components/leaflet_picker/`。浏览器中的 `L.Map` 只创建一次；marker 使用 `setLatLng`，route 只替换 route layer，图层只更新 value/style。路线 pane 高于道路风险与降雨 pane。在线/离线切换复用同一个地图实例并保留 OSM attribution。

`src/floodroute/ui/map_data.py` 负责只读查询。真实查询读取标准 `rainfall.csv`，按决策时间取每格网最新可用观测，关联 `grid_cells.csv`，再从当前 `RiskEngine` state 和正式道路特征提取解释。`Runtime.observed_state_with_sources` 只额外返回已用于原计算的 mapped rain frame；风险计算仍调用原 `RiskEngine.compute`。

静态展示资产由 `scripts/build_map_query_assets.py` 可重复生成，来源哈希和展示省略规则记录在 `data/derived/display/manifest.json`。资产只用于显示/查询，禁止作为路由或实验输入。

## 性能

浏览器使用 `performance.now()`，冷启动独立重启服务并禁用缓存；暖交互各10次。

| 指标 | median | p90 | 结论 |
|---|---:|---:|---|
| 页面外壳可见 | 353.3 ms | 795.8 ms | 通过 |
| 地图可交互 | 2434.5 ms | 2450.8 ms | 通过 |
| 起点 marker | 250.5 ms | 309.7 ms | 通过 |
| 终点 marker | 244.8 ms | 255.2 ms | 通过 |
| 信息查询 | 275.4 ms | 360.4 ms | 通过 |
| 路线和指标 | 279.4 ms | 310.6 ms | 通过 |

降雨层首次/暖开启为514.9/301.6 ms；道路风险层首次/暖开启为977.4/324.3 ms；OSM 瓦片 `loading→load` 为157 ms。所有交互、图层和瓦片切换保持同一个 map instance，`full_map_remount=false`。与 v1.1 相比热交互中位数未退化；冷地图中位数增加177.5 ms，仍低于3秒目标。

Python snapping 中位数约3–4 ms，routing约12.8 ms，首次查询构建58.9 ms，Leaflet绘制中位数约3–4 ms。主要余量是 Streamlit fragment rerun、组件消息传输和浏览器提交绘制。首次图层开启另含静态 GeoJSON 解析；外部瓦片延迟单列。

证据：[results/ui_end_to_end_performance_v2.json](results/ui_end_to_end_performance_v2.json) 和 [docs/UI_PERFORMANCE_REPORT.md](docs/UI_PERFORMANCE_REPORT.md)。

## 测试

全部 **105 项**测试通过。最初 v1.2 验收运行耗时 **37.606 秒**；发布门禁在 Windows 11 / Python 3.13.3 上重新运行，unittest 报告 **147.980 秒**。新增测试覆盖：

- 真实格网/正式道路/当前风险状态查询；
- rain 缺失保持 unknown，不用0替代；
- 不生成不支持的3h/6h/24h累计量；
- 查询不修改端点、不规划；
- 无效点击保护端点、旧结果和视口；
- 静态 geometry 与动态 payload 分离；
- 单一 Leaflet map、增量图层和 route 层级；
- 原有真实/模拟、Ground Truth 隔离、Trigger顺序、实验和路由回归。

测试日志位于本地 `work/v1_2_full_tests.log`；性能阈值没有写成易受机器波动影响的普通 unittest。

## 修改和新增文件

- UI/runtime：`src/floodroute/ui/app_v1_1.py`、`controller.py`、`map_data.py`、`resources.py`、`runtime.py`。
- 持久组件：`src/floodroute/ui/components/leaflet_picker/` 的 Python 边界、HTML、JavaScript和两份静态展示 GeoJSON。
- 配置/生成：`config/ui_v1_1.json`、`scripts/build_map_query_assets.py`、`data/derived/display/manifest.json`。
- 测试：`tests/test_map_data_query.py`、`test_ui_v1_1.py`、`test_ui_performance.py`。
- 结果：`results/ui_end_to_end_performance_v2.json`。
- 文档：README、本文、`docs/MAP_DATA_QUERY_GUIDE.md`、`DEMO_GUIDE.md`、`FINAL_ARCHITECTURE.md`、`UI_FINAL_REVIEW.md`、`UI_PERFORMANCE_REPORT.md`。

## 已知限制

- 真实快照当前降雨很弱，只验证真实动态数据链路，不能代表强降雨下的实测效果。
- 水位源未达到空间、时间和基准可验证要求，未进入道路风险。
- 格网展示使用官方中心构造的0.01°方格；这是源信息表声明的格网范围表达，不是测站覆盖精度声明。
- 道路风险展示省略 service 类并合并视觉重复反向线；查询/路由使用正式道路边，不把展示简化结果反馈给算法。
- 道路名称源存在乱码时隐藏为“暂无可靠数据”。
- 在线地图速度取决于 OSM 网络，系统 marker/route 不等待瓦片完成。
- 风险输出是道路内涝风险指数，不是积水深度、通行保证或真实导航预计时间。
- 受控场景和留出实验结论保持克制；不证明可信优先普遍最优或真实灾害下绝对安全。

## 人工验收边界

Chrome 核心交互已通过，见 [docs/UI_FINAL_REVIEW.md](docs/UI_FINAL_REVIEW.md)。没有单独人工确认的具体分辨率、显示器/硬件组合、回放全过程及额外浏览器版本仍保持 pending，不扩写为独立验收样本。
