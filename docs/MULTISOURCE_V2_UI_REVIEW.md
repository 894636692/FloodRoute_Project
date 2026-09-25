# Multisource V2 UI 人工验收

状态：**待用户人工复核**。自动化测试与代码检查不能代替浏览器中的最终人工判断，以下项目
不得自动勾选。

- [ ] 真实模式不出现模拟 water
- [ ] 多源模式同时显示 rain 与 water 两类 source
- [ ] 模拟积涝 sensor 可以点击
- [ ] sensor popup 显示具体 `water_level_index`
- [ ] sensor popup 显示 observation timestamp 与 `retrieved_at`
- [ ] missing 显示“暂无可靠数据/不可用”，不显示为 0
- [ ] 切换 delay 后 data time、age 与 status 正确变化
- [ ] 通信中断后对应 sensors 灰化或 unavailable
- [ ] 恢复演示后重新出现有效观测
- [ ] 多源路线规划成功
- [ ] 路线指标与当前路线对应
- [ ] 查看信息不会改变起点或终点
- [ ] 距道路超过 100 m 的非法选点保持旧 marker、route、center 与 zoom
- [ ] Chrome console 为 0 errors
- [ ] 多源数据更新前后 `mapInstanceId` 不变，L.Map 没有重新创建

## 已完成的自动检查（不替代上方复核）

- persistent component 源码只创建一次 `L.map(...)`，sensor layer 在现有 map 中更新；
- 真实场景仍固定显示“真实水位数据：未启用”；
- simulated sensor popup 明确标注“受控模拟”和“不代表真实道路积水深度”；
- 观测适配器只向 UI 返回 observed fields，不返回 H、B 或完整 latent truth；
- 既有非法点击、persistent map 与 UI 回归测试继续执行。
- 2026-09-25 浏览器自动检查：多源场景显示 `48/48` 个监测点，地图组件接收 48 条 sensor
  payload；点击 S048 后弹窗显示指数、观测时间、到达时间、信息年龄、quality、availability
  与“受控模拟”免责声明；
- 同一次浏览器检查中，切换在线底图前后 `mapInstanceId` 均为
  `leaflet-7mp7xslyytw`，组件更新时间变化而实例编号不变；Chrome 控制台捕获 0 个 error；
- 自动化点击地图后，前端已记录 `clickSentAt`，但该次浏览器连接未观察到 Streamlit 回传的
  marker 更新。因此起终点、路线与后续状态联动仍严格保留为人工 pending，不据此勾选。
