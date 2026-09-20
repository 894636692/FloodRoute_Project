# FloodRoute final v1 验收记录

日期：2026-09-20。分支：`integration/final-v1`。
Phase 0–13 的实现、数据链路和自动化验收完成；**浏览器目视验收待完成**。
main 和原始合作分支保留，未 merge A 独立历史，未 force push。
本轮提交在本地集成分支，尚未推送 GitHub。

## 已完成

- A 正式 LFS GPKG 成功取得、SHA256 验证：112,218 条有向边、46,468 个节点。
- A/B schema 隔离，静态质量标记和有效比例进入风险引擎；缺失值有明确先验和不确定性。
- 4,232 真实深圳格网、100,000 条小时降雨接入；全部原值保留，小时雨量全零。
- 121,153 条 Grid→Edge 相交映射，覆盖全部 A 道路，长度覆盖率约 100%。
- 真实水位/预报关闭，不产生缺失或过期惩罚。运行时不依赖 QGIS。
- 候选机动车道路筛选后保留 55,727 边；缓存节点空间索引和静态图，保留平行边 key。
- 真实三路线、可重复极端情景、45 组合独立实验、17 时刻 Trigger 回放、Streamlit 演示。
- 旧 MVP/路线/fixture 入口移入 legacy；正式静态输出不会被旧 fixture 默认路径覆盖。

## 自动化验收

当前 **57 项 unittest 全部通过**，包括原始回归、正式 A 接口、C 接口、映射、缺失/禁用源、
未来信息隔离、实验顺序不变性、真正触发后才寻路、冷却期、平行边、UI 两种场景和错误提示。
`pip check` 无依赖冲突。本地 Streamlit 服务 `/_stcore/health`返回 `ok`。
360 条独立实验和 51 条回放重复运行，除耗时字段外结果完全一致，见 `results/reproducibility.json`。
Windows/Python 3.13 依赖版本冻结于 `requirements-lock.txt`；CSV/JSON 使用 LF 保证跨平台输入哈希稳定。

## 实际运行结果

真实输入：2026-09-18T00:40:00+08:00，前一小时降雨全零。

| 方法 | 距离 m | 长度加权风险暴露 |
|---|---:|---:|
| shortest | 10,279.90 | 0.299035 |
| risk | 10,361.51 | 0.289612 |
| trusted | 10,361.51 | 0.289612 |

独立实验 360 行全部完成；以下为 source-specific tau 下 45 组合平均，不代表真实洪水验证：

| 方法 | 平均距离 m | 情景 truth exposure |
|---|---:|---:|
| shortest | 10,279.90 | 0.642191 |
| risk | 10,329.33 | 0.636361 |
| risk+uncertainty | 10,305.33 | 0.636316 |
| trusted | 10,294.55 | 0.638645 |

17 时刻固定 OD 回放（次数不含初始规划）：

| 策略 | 重规划 | 换路 | 平均情景风险暴露 | 平均距离 m |
|---|---:|---:|---:|---:|
| never | 0 | 0 | 0.547032 | 10,279.90 |
| always | 16 | 9 | 0.543238 | 10,314.97 |
| triggered | 2 | 0 | 0.547032 | 10,279.90 |

triggered 比 always 少 87.5% 的重规划，但风险暴露略高约 0.003794；候选改进不足，未实际换路。
这展示了当前配置的代价权衡，不证明 triggered 永远最安全，也不证明真实应急通行效果。
优化后真实路线搜索约几十毫秒（不含加载/建图）；准确本机耗时见结果 JSON。

## 数据边界及剩余事项

- 输出为 **road flood risk index，不是道路积水深度预测**。
- REAL 与 SIMULATED_SCENARIO 分文件、页面和来源记录。Truth 只用于情景生成和离线评价。
- 真实水位无合法公开坐标且时间/基准未验证；不接入道路真实风险。
- 雨量时区/累计窗口为用户确认，获取时刻未知；真实链路仅为快照接入验收。
- IMERG 无实际文件/凭证，已提供可选本地累计 TIFF 导入器，不阻塞核心实验。
- A 原始输入保留在原分支，本轮复用并验证正式产物，没有重新执行 GDAL 预处理。
- 未建模完整转向限制、交通、车辆约束；固定速度为估算。
- **目视验收阻塞**：浏览器连接返回 `nodeRepl.fetch request failed`。AppTest 与 HTTP 检查已通过，
  仍需打开页面检查地图显示、路线叠加和中文布局，不能视为已经目视通过。

## 运行命令

仓库根目录、激活环境后：

```shell
python -m pip install -r requirements-lock.txt
git lfs pull --include="data/derived/static/road_static_features.gpkg"
python -m unittest discover -s tests -v
python scripts/run_real_pipeline.py
python scripts/run_scenario_experiments.py
python scripts/run_trigger_replay.py
python scripts/run_demo.py
```

地图输入变化后：`python scripts/build_grid_mapping.py`。
演示地址：`http://127.0.0.1:8501`。详细说明见 `docs/DEMO_GUIDE.md`。
