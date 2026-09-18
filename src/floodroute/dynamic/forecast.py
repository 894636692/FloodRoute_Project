"""集合预报模块（后续阶段，当前仅占位）。

计划输出 forecast_ensemble.csv：
issued_at, valid_at, member_id, lon, lat, precipitation_mm, interval_min, source。
issued_at 为发布时间，valid_at 为预报有效时间；完整保留 member_id。
本模块不计算不确定性，也不构造延迟实验场景。
"""
