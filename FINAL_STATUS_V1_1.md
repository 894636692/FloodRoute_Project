# FloodRoute v1.1 最终状态

日期：2026-09-20。工作分支：`experiment-ui/v1.1`。

`manual_visual_review = pending`

自动化开发、留出实验、复现和服务检查已完成；浏览器目标屏幕验收待人工确认。

后续用户 Edge 截图确认旧版在线底图和已规划路线可见。本轮完成最终 UI 排版与地图性能修正：4+3指标、窄卡换行、路线聚焦、选点状态、紧凑状态栏、560px地图和持久 Leaflet 组件。Codex 内置 Chromium 浏览器已完成真实地图交互与端到端计时；用户人工检查表仍保持 `pending`。

## Git 与数据保护

- 稳定分支 `integration/final-v1` 与标签 `v1.0-engineering` 均保持在 `73cae1aaf0cfe33405b0536592e1a2d89486870c`。
- 本轮更改仅提交到 `experiment-ui/v1.1`，未修改 main；完成回归后同步到同名远端分支。
- 正式 GIS、真实动态数据与解析、风险核心、路由核心及 v1 配置对稳定标签无差异。原有未跟踪的用户资料保持原位。
- 原有 **78 项测试及断言全部保留**；新增18项性能架构测试验证持久地图和增量更新。最终 **96 项测试全部通过**（36.285秒），日志：`work/ui_e2e_regression_tests.log`。

## 本轮 UI/runtime 性能修正

- 浏览器端到端中位数：页面外壳 318.8 ms，地图可点击 2257.0 ms，起点 marker 266.3 ms，终点 marker 250.2 ms，路线和新指标 309.8 ms，全部达到本轮目标。
- 基线起点/终点/规划存在 6/10、8/10、10/10 次完整地图重挂载；改后 30/30 次保持同一个 iframe、document、Leaflet map 和容器，`full_map_remount = false`。
- Python 吸附中位数约 3 ms，routing 12.8 ms，Leaflet 状态渲染约 2–3 ms；其余约 0.25–0.30 秒来自 Streamlit rerun、消息传输与浏览器绘制的组合路径。
- 禁用缓存时，21 张在线 OSM 瓦片 335.5 ms 完成；marker/route 不等待瓦片，外部网络和内部交互已分开记录。
- 完整 HTML 体积：在线规划图约13.42 MB→25.6 KB，离线约13.42 MB→662.5 KB。正式55,727条候选路网不变；新增586,930 B的显示专用简化几何。
- 新增持久 Leaflet 组件，起终点使用 `setLatLng`、路线只替换 route layer；只有新路线才 fit bounds，普通选点保留视角。状态消息约 0.35–3.43 KB，不重新发送地图 HTML。原始/吸附位置和节点详情可折叠查看。
- 点击只吸附，不自动规划；条件变化保留旧结果并标记stale。动态数据、Runtime及长度索引缓存。启用工作区/地图fragment与配置form，最低Streamlit版本1.64，锁定环境版本不变。
- 动态回放算法及17时次不变；先生成帧再由定时fragment渲染单个地图组件。在线署名保留，离线不含瓦片层。
- 本轮没有运行完整Experiment v2，也没有修改其结果、所选参数、风险/寻路/Trigger核心、真实数据及原有78项测试。
- 服务已在本机8502重新启动，直连健康检查 `ok`。未操作其它端口的服务。

测量记录：`results/ui_performance_before.json`、`results/ui_performance_after.json`、`results/ui_end_to_end_performance.json`。详情见 [UI性能报告](docs/UI_PERFORMANCE_REPORT.md)；所有人工勾选项保持未勾选。

## 已完成

中文界面包含场景说明、中文策略、七项指标、风险解释和下载。经纬度输入框移除，地图点击吸附至真实候选机动车节点，阈值 500 米配置化，复用空间索引。保存点击位置、节点 ID、吸附位置和距离。清除、交换和已提交条件改变会使旧结果标记为过期，保留旧指标与原始下载来源，等待显式重新规划。

真实/模拟模式严格分开；真实模式隐藏扰动参数，模拟高级设置默认折叠。动态回放采用用户点击的固定起终点，先评估当前路线、再决定是否搜索，中文提示区分触发与实际换路。路线风险指标保持长度加权。完整 17 帧回放纳入 AppTest。

分组选参采用 2 个校准种子、2 个验证种子、3 个留出测试种子。四组候选中验证组选择均衡配置；测试不参与选参。4,320 条独立路线决策比较四种方法和三种时效性设置。

## 实验结果

- 真值平均暴露：最短路径 0.629783；风险优先 0.623220；风险＋不确定性 0.623782；可信优先 0.623920。**可信优先没有取得优势，原样保留结果。**
- 所选降雨时间尺度为 60 分钟，与统一尺度相同；只有降雨源启用，不能证明分数据源时间尺度更优。
- T1 三个测试种子均真正换路一次；触发式重规划 1 次，对照每次重规划 11 次。触发式平均暴露约 0.357056，不重规划约 0.399471。
- T2 触发式省去 11 次重复规划，平均暴露与每次重规划相同。两种策略都没有实际换路，故未验证“减少路线震荡”的额外结论。
- 第二次完整运行的 25 个结果文件除计时外一致。选参文件、真值数据和路线指标可复现，记录见 `results/experiment_v2/reproducibility.json`。
- 四张中文实验图已生成并逐张检查字体、图例与边距，附绘图数据及来源信息。

## 修改文件

- UI：`src/floodroute/ui/app_v1_1.py`、`controller.py`、`map_view.py`、`observations.py`；`scripts/run_demo.py`；`config/ui_v1_1.json`。
- 实验与基准：`src/floodroute/experiments/v2.py`、`benchmarks.py`；`config/experiment_v2.json`、`selected_v1_1.json`；`scripts/run_experiment_v2.py`、`run_trigger_benchmarks.py`、`plot_experiment_v2.py`、`check_v1_1_reproduction.py`。
- 测试：`tests/test_ui_v1_1.py`、`test_experiment_v2.py`、`test_benchmarks_v1_1.py`。
- 依赖：`requirements.txt`、`requirements-lock.txt` 增加 Folium 与 Streamlit 地图组件及依赖。
- 结果：`results/experiment_v2/` 的划分、协议、选参、路线、基准、复现记录与中文图。
- 文档：README、FINAL_STATUS、本文、`docs/DEMO_GUIDE.md`、`FINAL_ARCHITECTURE.md`、`EXPERIMENT_V2_REPORT.md`、`UI_FINAL_REVIEW.md`。

## 运行与剩余限制

```shell
python scripts/run_demo.py --server.port=8502
python -m unittest discover -s tests -q
```

本机服务 `http://127.0.0.1:8502` 已启动，健康检查返回 `ok`。本轮没有停止其它端口服务。

2026-09-20 已恢复 Codex 内置浏览器连接，实际完成地图起终点点击、吸附、规划聚焦、在线/离线切换、三种视口布局和动态回放到末时次的复验；发现并修正交换起终点时视角回退的问题。随后完成 3 次冷启动和 30 次热交互端到端性能验收。Chrome/Edge 扩展专项验收不声明通过；用户人工检查表继续保持待填写。详情见 [UI 验收](docs/UI_FINAL_REVIEW.md)。Leaflet、离线道路和 OSM 署名资源均随组件或页面正确加载。

本实验只有三个留出种子、两组起终点且共享场景家族，不支持总体优越性或真实灾害安全结论。当前真实降雨较弱，水位源仍因语义问题关闭；不包含真实水深、完整转向关系、实时交通限制或真正导航预计时间。

详细证据：[UI 验收](docs/UI_FINAL_REVIEW.md)、[UI性能报告](docs/UI_PERFORMANCE_REPORT.md)、[实验报告](docs/EXPERIMENT_V2_REPORT.md)。
