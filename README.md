# 涝途智避 · FloodRoute v1.2 / Research v1.3

面向异步多源信息可信度的道路内涝风险与触发式路径规划研究原型。
**输出是 road flood risk index，不是道路积水深度预测。**

正式稳定版本由 `main` 与标签 `v1.2.0` 标识。开发历史保留远端分支 `integration/final-v1`、`experiment-ui/v1.1`、`experiment-ui/v1.2`，以及标签 `v1.0-engineering`。
本轮在持久 Leaflet 地图上增加 100 米有效道路选点、任意位置查询、真实降雨格网和道路风险解释图层；正式 GIS、真实降雨、风险/路由核心和既有实验结果保持不变。

研究验证版本位于 `research-validation/v1.3`，完成后由标签 `v1.3.0-research` 固定。它在 v1.2.0 冻结参数上增加深圳 2023-09-07/08 历史事件外部排序检查和 27,648 条路线的扩展受控验证；`main` 继续保持工程稳定版，不把研究验证直接覆盖到发布分支。

## 快速运行

仓库根目录、已激活的 Python 环境：

```shell
python -m pip install -r requirements.txt
git lfs pull --include="data/derived/static/road_static_features.gpkg"
python -m unittest discover -s tests -v
python scripts/run_demo.py
```

浏览器打开 `http://127.0.0.1:8501`。默认本地道路地图不需要底图 API Key。
可先打开“降雨格网”或“道路风险”，用“查看信息”查询具体降雨和附近正式道路特征；再在道路附近点击起终点并规划。旧 `src/floodroute/ui/app.py` 只作历史回归测试；启动脚本指向新界面。
若 8501 已占用：`python scripts/run_demo.py --server.port=8502`。
Windows / Python 3.13 已验收版本见 `requirements-lock.txt`，可用 `pip install -r requirements-lock.txt`。
运行时不需要 QGIS/osgeo；A 的原始预处理重建需要 GDAL Python。

## 正式入口

```shell
python scripts/run_real_pipeline.py
python scripts/run_scenario_experiments.py
python scripts/run_trigger_replay.py
python scripts/run_demo.py
```

| 数据 | 属性 | 状态 |
|---|---|---|
| A GPKG，112,218 条有向边 | DERIVED_FROM_REAL | LFS 哈希/schema 验收通过 |
| 深圳 4,232 格网、100,000 条降雨 | REAL | 小时累计雨量全零，正式接入 |
| Grid→Edge，121,153 条映射 | DERIVED_FROM_REAL | 道路长度覆盖率约 100% |
| 55,727 条候选机动车道路边 | DERIVED_FROM_REAL | 排除步道、台阶、施工和明确通行限制 |
| 17 时刻受控极端降雨 | SIMULATED_SCENARIO | 固定种子，truth/observed 分离 |
| 2023-09-07/08 NASA POWER 历史强迫 | REAL_HISTORICAL_COARSE_FORCING | MERRA-2 小时值；区域级外部验证，不是道路实测 |
| 3 类 × 12 种子扩展场景 | SIMULATED_EXPANDED_VALIDATION | 冻结参数、8 OD、配对观测、27,648 条路线 |
| IMERG 区域强迫 | OPTIONAL_EXTERNAL | 需要 Earthdata 授权，本次未使用 |

真实水位缺少合法公开坐标、时间语义及基准，`water.active=false`，不参与惩罚。
真实雨量时间语义由项目负责人确认、获取时刻未知；真实链路证明快照接入，不证明历史实时可用性。

## 结果与文档

v1.1 新实验：`python scripts/run_experiment_v2.py`，随后运行 `python scripts/plot_experiment_v2.py` 生成中文图。
只重跑冻结参数的触发基准：`python scripts/run_trigger_benchmarks.py`。
完整复现另存目录：`python scripts/run_experiment_v2.py --output work/experiment_v2_reproduction`。
研究验证入口：

- [最终研究摘要](docs/FINAL_RESEARCH_SUMMARY.md) 与 [最终研究状态](FINAL_RESEARCH_STATUS.md)；
- [深圳历史事件验证](docs/HISTORICAL_EVENT_VALIDATION.md)，结果在 `results/historical_validation/`；
- [冻结参数扩展验证](docs/EXPANDED_FROZEN_VALIDATION.md)，结果在 `results/expanded_validation/`。

工程发布资料见 `results/experiment_v2/`、[v1.2 验收](FINAL_STATUS_V1_2.md)、[v1.2 发布说明](docs/RELEASE_V1_2.md)、[地图查询指南](docs/MAP_DATA_QUERY_GUIDE.md)、[实验报告](docs/EXPERIMENT_V2_REPORT.md)。以下保留 v1 结果。

- `results/real_pipeline/`：三种路线、指标和来源哈希。
- `results/scenario_experiments/independent.csv`：45 组合 × 4 基线 × 2 tau = 360 条。
- `results/trigger_replay/`：17 时刻 × 3 策略 = 51 条。
- `results/reproducibility.json`：两次完整运行的非耗时结果一致。
- [最终验收](FINAL_STATUS.md)、[逐阶段记录](docs/INTEGRATION_STATUS.md)。

输入变更后用 `python scripts/build_grid_mapping.py` 重建映射。运行时检查哈希，拒绝过期映射。
旧代码和原始 MVP README 均在 `legacy/`，禁止作为正式实验入口。

详见 [架构](docs/FINAL_ARCHITECTURE.md)、[数据来源](docs/DATA_PROVENANCE.md)、
[实验协议](docs/EXPERIMENT_PROTOCOL.md)、[限制](docs/LIMITATIONS.md)、[演示指南](docs/DEMO_GUIDE.md)。
