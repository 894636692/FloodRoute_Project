# FloodRoute / 涝途智避 v1.2.0 发布说明

发布日期：2026-09-21。发布标签：`v1.2.0`。发布实现提交：`0aa63c824db37deb0f3720f67bdac778d53d5f25`。

## 环境与安装

正式验收环境为 Windows 11 64 位、Python 3.13.3。Windows 环境优先使用锁定依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
git lfs pull
python -m pip check
python -m unittest discover -s tests -q
python scripts/run_demo.py
```

核心正式道路文件 `data/derived/static/road_static_features.gpkg` 由 Git LFS 管理；克隆后必须执行 `git lfs pull`。运行 UI 不需要 QGIS/GDAL Python，重建 A 组原始静态 GIS 才需要对应预处理环境。

## 发布内容

- 正式深圳道路、DEM、WorldCover 与 4,232 个真实气象格网的数据链路。
- 道路内涝风险指数、shortest/risk/trusted 路由、Freshness、Uncertainty 与 Trigger replay。
- 持久 Leaflet 中文 UI、100 米道路选点、路线自动聚焦、任意位置查询、降雨格网和道路风险解释。
- Experiment v2、可复现结果、中文图表、数据来源与限制文档。

## 测试与 CI

- `python -m pip check`：通过。
- 105 项单元/回归测试全部通过；Windows 11 / Python 3.13.3 发布门禁的 unittest 报告时间为 147.980 秒。
- GitHub Actions 使用 `windows-latest`、Python 3.13、Git LFS、`requirements-lock.txt`，只运行依赖检查和工程回归测试；不运行浏览器 GUI、外部下载、人工交互或长时间完整实验。
- Google Chrome 核心人工验收已通过，具体事实与未单独检查项目见 `docs/UI_FINAL_REVIEW.md`。

## 数据与实验说明

项目输出是**道路内涝风险指数**，不是道路积水深度预测、真实通行安全概率或水动力模型。真实水位仍为 `water.active=false`，因为公开数据尚未同时满足可验证坐标、明确时间语义和明确测量基准。

真实深圳当前降雨快照主要用于验证真实动态数据链路，不能代表极端暴雨效果。受控极端降雨、观测延迟、缺失、噪声与 Trigger 实验属于可重复模拟条件；Ground Truth 只用于离线评价，Planner 不得读取。

冻结参数来自 `config/selected_v1_1.json`，SHA256：

`6BF703FB88A01640BE4347A84C8BF608D41F2A55169484DA0ECE6EACC692E4E6`

## 已知限制

- 当前真实快照降雨较弱，不验证真实极端暴雨下的道路风险效果。
- 真实水位、厘米级积水深度与真实负样本道路均不可用。
- 道路风险图层为科研解释和相对比较，不构成应急导航安全承诺。
- 在线底图速度受 OSM 网络影响；离线模式不含在线瓦片。
- 公开灾情报道尚未纳入 v1.2.0；历史事件外部验证将在独立验证分支完成，不改动此标签。
