"""Precompute metric line/polygon intersections once, never nearest grid centres."""
from pathlib import Path
import hashlib
import json
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

EDGE = ['u', 'v', 'key']


def grid_polygons(path: str | Path) -> gpd.GeoDataFrame:
    cells = pd.read_csv(path, dtype={'grid_id': str})
    aliases = {'格网左下角经度（度）':'X1', '格网左下角纬度（度）':'Y1',
               '格网右上角经度（度）':'X2', '格网右上角纬度（度）':'Y2'}
    cells = cells.rename(columns=aliases)
    if cells.grid_id.duplicated().any() or not cells.crs.eq('EPSG:4326').all():
        raise ValueError('Grid identifiers/CRS invalid')
    bounds = cells[['X1','Y1','X2','Y2']].to_numpy(float)
    if not np.isfinite(bounds).all() or not ((cells.X1 < cells.X2) & (cells.Y1 < cells.Y2)).all():
        raise ValueError('Invalid grid bounds')
    polygons = shapely.box(*bounds.T)
    return gpd.GeoDataFrame(cells, geometry=polygons, crs=4326).to_crs(32650)


def build_mapping(edges, grids):
    """Return edge-grid rows, all-edge coverage, and length-weighted summary.

    Weights normalize covered length; coverage remains separate so partial coverage
    is never presented as complete. A line exactly on a cell boundary shares weights.
    """
    if edges.crs.to_epsg() != 32650 or grids.crs.to_epsg() != 32650:
        raise ValueError('Both inputs must use EPSG:32650')
    if edges.duplicated(EDGE).any():
        raise ValueError('Duplicate edge IDs')
    edges = edges.reset_index(drop=True)
    grids = grids.reset_index(drop=True)
    left, right = grids.sindex.query(edges.geometry, predicate='intersects')
    pieces = shapely.intersection(edges.geometry.values[left], grids.geometry.values[right])
    lengths = shapely.length(pieces)
    good = lengths > 1e-7
    left, right, lengths = left[good], right[good], lengths[good]
    weights = edges.iloc[left][EDGE].reset_index(drop=True)
    weights['grid_id'] = grids.iloc[right].grid_id.to_numpy()
    weights['overlap_length_m'] = lengths
    weights['weight'] = lengths / weights.groupby(EDGE).overlap_length_m.transform('sum')
    coverage = edges[EDGE + ['length_m']].copy()
    # union avoids counting cell boundaries twice when measuring actual coverage.
    union = shapely.union_all(grids.geometry.values)
    covered = shapely.length(shapely.intersection(edges.geometry.values, union))
    coverage['covered_length_m'] = np.minimum(covered, edges.length_m)
    coverage['coverage_fraction'] = coverage.covered_length_m / coverage.length_m
    ratio = float(coverage.covered_length_m.sum() / coverage.length_m.sum())
    report = {'crs': 'EPSG:32650', 'edge_count':len(edges), 'mapped_edges':len(weights.groupby(EDGE)),
              'mapping_rows':len(weights), 'road_length_coverage':ratio,
              'decision':'retain_study_area' if ratio >= .95 else 'manual_review_required' if ratio < .90 else 'retain_with_partial_coverage_flags',
              'uncovered_edges':int(coverage.coverage_fraction.lt(.999).sum())}
    return weights.sort_values(EDGE+['grid_id']).reset_index(drop=True), coverage, report


def fingerprint(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save_mapping(edges, grids, output, sources):
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    weights, coverage, report = build_mapping(edges, grids)
    report['input_sha256'] = {str(p).replace('\\','/'): fingerprint(p) for p in sources}
    weights.to_parquet(output, index=False)
    coverage.to_parquet(output.with_name('edge_coverage.parquet'), index=False)
    output.with_name('coverage_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report
