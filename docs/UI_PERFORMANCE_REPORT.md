# UI 端到端性能验收报告

日期：2026-09-20。分支：`experiment-ui/v1.1`。人工目视验收：**pending**。

本轮只优化地图的装载与状态更新路径。风险、Routing、Trigger、实验参数、实验结果和真实数据均未修改。测量使用浏览器 `performance.now()`，从用户动作开始计时，到页面上 marker、路线或指标真正可见为止；Python 计时只作为其中的诊断子阶段。

## 验收方法

- 浏览器：Codex In-app Browser（Chromium），视口 1920×1200。
- 冷启动：3 次。每次关闭旧测试服务、重新启动 Streamlit、禁用浏览器缓存，再打开一个新 URL。
- 热交互：起点点击 10 次、终点点击 10 次、路线规划 10 次。
- 可见完成条件：目标 marker/路线和指标出现，并连续经过 3 次 `requestAnimationFrame`。
- p90：线性插值，位置 `(n-1)×0.9`。
- 在线瓦片：禁用浏览器缓存，单独记录 Leaflet `loading`/`load` 事件和 Resource Timing；不把瓦片时间混入应用内部延迟。
- 原始捕获保存在本地 `work/ui_e2e_*.json`；可提交汇总为 `results/ui_end_to_end_performance.json`。

基线的 10 条误分类终点事件和 1 条未造成 marker 变化的重复点击已排除并重新测量，排除原因与数量写入汇总 JSON。冷启动基线第 3 次出现 21.3 秒页面外壳、25.5 秒地图可交互的真实异常值；报告保留原值，因此 n=3 的基线 p90 很高，不将其隐藏为“平均表现”。

## 用户可见结果

| 指标 | 修改前 median / p90 / min / max | 修改后 median / p90 / min / max | 目标 | 结论 |
|---|---:|---:|---:|---|
| 页面外壳可见（3次） | 1437.6 / 17297.8 / 1360.9 / 21262.8 ms | 318.8 / 320.9 / 292.7 / 321.4 ms | median < 1000 ms | 通过 |
| 地图可点击（3次） | 6322.9 / 21660.3 / 6094.6 / 25494.6 ms | 2257.0 / 2265.1 / 2228.9 / 2267.1 ms | 尽量 < 3000 ms、约不超过 5000 ms | 通过 |
| 起点 marker 可见（10次） | 1708.4 / 2263.0 / 1577.7 / 2344.7 ms | 266.3 / 277.5 / 244.8 / 301.1 ms | median < 500、p90 < 1000 ms | 通过 |
| 终点 marker 可见（10次） | 2275.6 / 2328.4 / 1526.3 / 2355.0 ms | 250.2 / 266.1 / 241.6 / 285.0 ms | median < 500、p90 < 1000 ms | 通过 |
| 路线与新指标可见（10次） | 2885.6 / 2930.4 / 1809.4 / 2947.9 ms | 309.8 / 337.2 / 298.9 / 379.5 ms | median < 1000 ms | 通过 |

中位数降幅分别为：页面外壳 77.8%，地图可点击 64.3%，起点点击 84.4%，终点点击 89.0%，路线规划 89.3%。

## 地图生命周期结论

基线确实存在完整重挂载，因此 `full_map_remount = true`：起点点击 6/10、终点点击 8/10、路线规划 10/10 发生 iframe、document、Leaflet map 和地图容器一起更换。

优化后的 30 次热交互全部满足：

- `full_map_remount = false`；iframe、document、Leaflet map、地图容器 ID 始终不变。
- 点击起点/终点不会重新初始化 zoom/center；规划完成才按新路线执行 `fitBounds`。
- 离线点击没有瓦片请求；在线瓦片层由持久组件独立管理。
- 起终点更新调用 `setLatLng`；路线更新只替换 route layer。
- 起点状态消息约 345–348 B，终点约 385–388 B，路线状态消息约 3425–3427 B。
- 状态消息均为 JSON；`html_payload = false`，没有重新发送整张地图 HTML。

实现位于 `src/floodroute/ui/components/leaflet_picker/`。本地 Leaflet 1.9.4 资源与离线展示道路随组件加载，浏览器中的 `L.Map` 只创建一次。Streamlit rerun 仍会更新页面状态，但不再销毁地图。

## 内部、后端与瓦片分解

| 子阶段 | median / p90 / min / max |
|---|---:|
| Python 起点吸附 | 3.0 / 3.9 / 2.7 / 8.7 ms |
| Python 终点吸附 | 2.9 / 3.3 / 2.6 / 4.0 ms |
| Python 路由 | 12.8 / 14.1 / 12.3 / 17.2 ms |
| Leaflet 起点状态渲染 | 4.9 / 6.6 / 2.9 / 7.0 ms |
| Leaflet 终点状态渲染 | 4.2 / 6.1 / 1.3 / 11.0 ms |
| Leaflet 路线状态渲染 | 2.3 / 11.2 / 1.4 / 12.0 ms |

用户可见总耗时减去 Python 子阶段后，起点、终点、路线的中位数分别为 263.1、247.6、296.6 ms。这一余量包含 Streamlit rerun、WebSocket/组件消息调度和浏览器绘制，无法仅凭单个时钟再精确拆成三项，所以 JSON 使用 `streamlit_transport_and_browser_residual` 命名，避免误称为纯渲染耗时。

禁用缓存的在线 OSM 测量加载 21 张瓦片：从切换在线底图前到全部完成为 335.5 ms；Leaflet `loading` 到 `load` 为 166.4 ms；最长单张资源 164.0 ms；测量结束时待加载 0 张。组件状态渲染只用 5.7 ms。Marker 和路线属于独立 Leaflet layer，不等待瓦片下载，因此 `external_tile_latency` 与 `internal_interaction_latency` 已解耦。

## 改动

1. 在页面标题和侧栏框架显示后，后台预加载 Runtime；首次地图先显示轻量组件和“地图正在加载……”，不等待图、空间索引和动态表初始化。
2. 用最小持久 Leaflet 组件替换 `streamlit-folium` 地图输出。Python 只发送 marker、route、bounds、瓦片模式、revision 和后端诊断时间。
3. 地图点击只把经纬度与 request ID 发给 Streamlit；Python 吸附后返回吸附点，前端只更新对应 marker。
4. 在线瓦片层独立开关；离线道路从本地组件资产读取。Marker/route 更新不触发 tile layer 重建。
5. 增加浏览器探针、仅本机诊断服务和汇总脚本。正式服务仍由 `scripts/run_demo.py` 启动。

## 瓶颈判断

修改前首要瓶颈是 `streamlit-folium` iframe/Leaflet 完整重挂载和大地图 HTML 序列化。修改后它已消失。热交互中 Python 只占约 3–13 ms，Leaflet 更新约 2–12 ms；剩余约 0.25–0.30 秒主要位于 Streamlit rerun、组件消息传输和浏览器提交绘制的组合路径。该余量已达到本轮目标，没有证据支持继续修改算法或数据。

首次地图约 2.26 秒，主要仍是 Streamlit 首次会话、组件 iframe 和本地地图资产初始化。在线瓦片本次为 0.34 秒，且不阻塞 marker/route；若用户网络环境更慢，应单独归因为外部 tile 网络，而不是 Python snapping/routing。

## 回归与复现

性能阈值没有写入普通单元测试，避免机器与网络波动造成假失败。架构测试检查持久组件只创建一次地图、使用增量 marker/route 更新、应用不再调用 `st_folium`，并保留全部原功能测试。

```powershell
.\.venv\Scripts\python.exe scripts\summarize_ui_performance.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
python scripts/run_demo.py --server.port=8502
```

汇总证据：[ui_end_to_end_performance.json](../results/ui_end_to_end_performance.json)。人工检查表仍在 [UI_FINAL_REVIEW.md](UI_FINAL_REVIEW.md)，所有项目继续保持未勾选。
