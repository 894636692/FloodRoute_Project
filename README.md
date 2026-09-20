# 涝途智避 · FloodRoute v1

面向异步多源信息可信度的道路内涝风险与触发式路径规划研究原型。
**输出是 road flood risk index，不是道路积水深度预测。**

集成分支：`integration/final-v1`。从 C 分支建立，选择性迁移 A，未合并 A 的独立历史，未修改 main。

## 快速运行

仓库根目录、已激活的 Python 环境：

```shell
python -m pip install -r requirements.txt
git lfs pull --include="data/derived/static/road_static_features.gpkg"
python -m unittest discover -s tests -v
python scripts/run_demo.py
```

浏览器打开 `http://127.0.0.1:8501`。默认本地道路地图不需要底图 API Key。
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
| IMERG 区域强迫 | OPTIONAL_EXTERNAL | 仅导入器，无实际文件 |

真实水位缺少合法公开坐标、时间语义及基准，`water.active=false`，不参与惩罚。
真实雨量时间语义由项目负责人确认、获取时刻未知；真实链路证明快照接入，不证明历史实时可用性。

## 结果与文档

- `results/real_pipeline/`：三种路线、指标和来源哈希。
- `results/scenario_experiments/independent.csv`：45 组合 × 4 基线 × 2 tau = 360 条。
- `results/trigger_replay/`：17 时刻 × 3 策略 = 51 条。
- `results/reproducibility.json`：两次完整运行的非耗时结果一致。
- [最终验收](FINAL_STATUS.md)、[逐阶段记录](docs/INTEGRATION_STATUS.md)。

输入变更后用 `python scripts/build_grid_mapping.py` 重建映射。运行时检查哈希，拒绝过期映射。
旧代码和原始 MVP README 均在 `legacy/`，禁止作为正式实验入口。

详见 [架构](docs/FINAL_ARCHITECTURE.md)、[数据来源](docs/DATA_PROVENANCE.md)、
[实验协议](docs/EXPERIMENT_PROTOCOL.md)、[限制](docs/LIMITATIONS.md)、[演示指南](docs/DEMO_GUIDE.md)。
