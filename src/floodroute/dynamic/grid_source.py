"""Strict grid rainfall input contract; no invented stations or retrieval time."""
from pathlib import Path
import pandas as pd
from floodroute.common.schema import parse_iso8601

GRID_FIELDS = {'grid_id','spatial_type','coordinate_role','timestamp','window_start',
               'rain_mm','interval_min','lon','lat','source','quality_flag','retrieved_at'}


def read_rainfall(path: str | Path) -> pd.DataFrame:
    data = pd.read_csv(path, dtype={'grid_id': str})
    missing = GRID_FIELDS - set(data)
    if missing:
        raise ValueError(f'Missing grid rainfall fields: {missing}')
    for col in ('timestamp', 'window_start'):
        # Require explicit timezone before conversion: pandas UTC alone accepts naive input.
        for value in data[col].unique():
            parse_iso8601(str(value))
        data[col] = pd.to_datetime(data[col], utc=True)
    duration = (data.timestamp - data.window_start).dt.total_seconds() / 60
    if not duration.eq(data.interval_min).all() or not data.interval_min.eq(60).all():
        raise ValueError('v1 requires documented preceding-hour accumulation')
    if data.duplicated(['grid_id', 'timestamp']).any():
        raise ValueError('Duplicate grid/time: resolve conflicts explicitly before planning')
    if not data.spatial_type.eq('interpolated_observation_grid').all():
        raise ValueError('Unexpected source spatial type')
    return data.sort_values(['timestamp','grid_id']).reset_index(drop=True)
