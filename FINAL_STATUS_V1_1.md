# FloodRoute v1.1 最终状态

日期：2026-09-20。工作分支：`experiment-ui/v1.1`。

`manual_visual_review = pending`

自动化开发、留出实验、复现和服务检查已完成；浏览器目标屏幕验收待人工确认。

## Git 与数据保护

- 稳定分支 `integration/final-v1` 与标签 `v1.0-engineering` 均保持在 `73cae1aaf0cfe33405b0536592e1a2d89486870c`。
- 本轮更改仅在新分支上分任务提交，未修改 main，未推送远端。
- 正式 GIS、真实动态数据与解析、风险核心、路由核心及 v1 配置对稳定标签无差异。原有未跟踪的用户资料保持原位。
- 原 57 项测试全部保留，旧界面继续用于历史回归；新增 21 项，总计 **78 项测试通过**。

## 已完成

中文界面包含场景说明、中文策略、七项指标、风险解释和下载。经纬度输入框移除，地图点击吸附至真实候选机动车节点，阈值 500 米配置化，复用空间索引。保存点击位置、节点 ID、吸附位置和距离。清除、交换和条件改变会使旧结果失效。

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

本机服务 `http://127.0.0.1:8502` 已启动，健康检查返回 `ok`。原有 8501 服务未停止。

浏览器工具无法连接，尚未取得新界面屏幕截图。真实鼠标点选、在线瓦片加载、在线/离线视觉差异和用户屏幕布局需按 [演示指南](docs/DEMO_GUIDE.md) 人工确认，不能用自动化状态检查代替。离线模式没有瓦片层，但首次加载组件仍可能依赖第三方脚本。

本实验只有三个留出种子、两组起终点且共享场景家族，不支持总体优越性或真实灾害安全结论。当前真实降雨较弱，水位源仍因语义问题关闭；不包含真实水深、完整转向关系、实时交通限制或真正导航预计时间。

详细证据：[UI 验收](docs/UI_FINAL_REVIEW.md)、[实验报告](docs/EXPERIMENT_V2_REPORT.md)。
