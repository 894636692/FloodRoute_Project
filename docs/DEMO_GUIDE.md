# 演示指南

仓库根目录激活 Python 环境，运行：

```shell
python scripts/run_demo.py
```

浏览器打开 `http://127.0.0.1:8501`。改端口：`python scripts/run_demo.py --server.port=8502`。
按 Ctrl+C 停止。

1. 选择“真实深圳降雨 · REAL”，选最后时刻，保持默认起终点。
2. 切换 shortest/risk/trusted，查看距离、风险暴露、可信度、新鲜度和不确定性。
   真实雨量为零是样本事实，差异主要来自静态特征及代价权重。
3. 切换“受控极端情景 · SIMULATED”，选中间时刻并调整延迟。页面明确显示模拟标识。
   前期没有足够历史观测时，低可信度符合预期。
4. 展开 Trigger 记录，比较三种策略规划和换路次数。它是固定 OD 的预计算实验，
   与上方任意起终点的单次规划分开。
5. 下载路线 GeoJSON。显示 WGS84，内部距离和空间计算 UTM 50N。

地图默认使用本地道路轮廓，无须 API Key。可选在线底图依赖网络。
蓝/橙点是请求位置，路线端点吸附到候选机动车路网。超过网络 2 km、不连通或吸附到同一节点会提示。
旅行时间以 8 m/s 估算；路线不代表实际涉水通行安全。

若 GPKG 只有百余字节，执行 README 的 LFS pull。映射过期时运行
`python scripts/build_grid_mapping.py`，不要用 legacy fixture 替代正式 A 文件。

自动化已验收页面计算、真实/模拟切换和错误提示。浏览器连接不可用，目标屏幕的地图渲染、
中文布局及缩放仍待人工目视验收，已记录于 FINAL_STATUS。
