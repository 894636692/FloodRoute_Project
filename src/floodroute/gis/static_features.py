"""Rebuild the A -> B interface from immutable raw OSM/DEM/WorldCover."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

import networkx as nx
import numpy as np
from osgeo import gdal, ogr, osr

from floodroute.common.schema import (
    COMPUTE_CRS, SCHEMA_VERSION, INT_FIELDS, FLOAT_FIELDS, TEXT_FIELDS,
    NORMALIZED_FIELDS, FEATURE_FIELDS, REQUIRED_FIELDS,
)

NODATA = -9999.0
WC_CLASSES = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)
TIFF_OPTIONS = ["COMPRESS=LZW", "TILED=YES"]


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def spatial_ref(code):
    srs = osr.SpatialReference()
    srs.SetFromUserInput(code)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def read_area(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if len(data.get("features", [])) != 1:
        raise ValueError("study_area must contain exactly one feature")
    feature = data["features"][0]
    props = feature.get("properties", {})
    if not {"name", "version", "test_only", "final_area"}.issubset(props):
        raise ValueError("Missing study area metadata")
    geometry = ogr.CreateGeometryFromJson(json.dumps(feature["geometry"]))
    if geometry.GetGeometryName() not in {"POLYGON", "MULTIPOLYGON"} or not geometry.IsValid():
        raise ValueError("study_area must be a valid polygon")
    if "crs" in data and "4326" not in json.dumps(data["crs"]):
        raise ValueError("study_area must be EPSG:4326")
    projected = geometry.Clone()
    projected.Transform(osr.CoordinateTransformation(spatial_ref("EPSG:4326"), spatial_ref(COMPUTE_CRS)))
    return projected, props


def grid_for_area(area, resolution):
    xmin, xmax, ymin, ymax = area.GetEnvelope()
    return tuple((math.floor(v / resolution) if i < 2 else math.ceil(v / resolution)) * resolution
                 for i, v in enumerate((xmin, ymin, xmax, ymax)))


def build_rasters(root, config, out, area):
    bounds = grid_for_area(area, config["resolution_m"])
    for kind, pattern, resample, dtype, nodata in (
        ("dem", config["dem_glob"], "bilinear", gdal.GDT_Float32, NODATA),
        ("worldcover", config["worldcover_glob"], "near", gdal.GDT_Byte, 0),
    ):
        inputs = sorted(root.glob(pattern))
        if not inputs:
            raise FileNotFoundError(pattern)
        result = gdal.Warp(str(out / f"{kind}_30m.tif"), [str(p) for p in inputs],
            format="GTiff", dstSRS=COMPUTE_CRS, outputBounds=bounds,
            xRes=config["resolution_m"], yRes=config["resolution_m"],
            cutlineDSName=str(root / config["study_area"]),
            resampleAlg=resample, outputType=dtype, dstNodata=nodata,
            creationOptions=TIFF_OPTIONS)
        if result is None:
            raise RuntimeError(f"Failed to build {kind}")
        result = None
    # Both vertical and horizontal units are meters in this projected grid.
    result = gdal.DEMProcessing(str(out / "slope_deg.tif"), str(out / "dem_30m.tif"),
        "slope", scale=1.0, computeEdges=False, creationOptions=TIFF_OPTIONS)
    if result is None:
        raise RuntimeError("Slope generation failed")
    result = None
    arrays, grids = {}, {}
    for name, filename in (("dem", "dem_30m.tif"), ("slope", "slope_deg.tif"), ("worldcover", "worldcover_30m.tif")):
        ds = gdal.Open(str(out / filename))
        arr = ds.ReadAsArray().astype(float)
        arr[arr == ds.GetRasterBand(1).GetNoDataValue()] = np.nan
        arrays[name] = arr
        grids[name] = {"transform": list(ds.GetGeoTransform()), "width": ds.RasterXSize,
                       "height": ds.RasterYSize, "crs": ds.GetSpatialRef().GetAuthorityCode(None),
                       "nodata": ds.GetRasterBand(1).GetNoDataValue()}
        ds = None
    if len({json.dumps({k: v for k, v in grid.items() if k != "nodata"}, sort_keys=True) for grid in grids.values()}) != 1:
        raise ValueError("Raster grids are not aligned")
    return arrays, grids


def direction(tags):
    value = str(tags.get("oneway", "")).lower()
    if value in {"reversible", "alternating"} or "oneway:conditional" in tags:
        return "unsupported"
    if value in {"no", "false", "0"}:
        return "both"
    if value in {"-1", "reverse"}:
        return "reverse"
    if value in {"yes", "true", "1"}:
        return "forward"
    if value:
        return "unsupported"
    if tags.get("junction") in {"roundabout", "circular"} or tags.get("highway") in {"motorway", "motorway_link"}:
        return "forward"
    return "both"


def build_osm_graph(raw, area):
    elements = raw["elements"]
    ways = sorted((e for e in elements if e["type"] == "way" and e.get("tags", {}).get("highway")), key=lambda w: w["id"])
    points = {int(e["id"]): (float(e["lon"]), float(e["lat"])) for e in elements if e["type"] == "node"}
    membership = Counter()
    for way in ways:
        membership.update(set(way["nodes"]))
        for node, coord in zip(way["nodes"], way.get("geometry", [])):
            if coord:
                points.setdefault(node, (coord["lon"], coord["lat"]))
    tx = osr.CoordinateTransformation(spatial_ref("EPSG:4326"), spatial_ref(COMPUTE_CRS))
    projected = {node: tx.TransformPoint(*xy)[:2] for node, xy in points.items()}
    inside = {}
    for node, xy in projected.items():
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint_2D(*xy)
        inside[node] = bool(area.Intersects(point))
    graph = nx.MultiDiGraph(crs=COMPUTE_CRS, schema_version=SCHEMA_VERSION, topology="OSM ways split at shared nodes and boundary transitions")
    counts = Counter(raw_highway_ways=len(ways))
    records = []
    for way in ways:
        nodes = way["nodes"]
        tags = way["tags"]
        travel = direction(tags)
        if travel == "unsupported":
            counts["excluded_conditional_direction_ways"] += 1
            continue
        if any(node not in projected for node in nodes):
            raise ValueError(f"Way {way['id']} contains missing node coordinates")
        repeats = Counter(nodes)
        cuts = {0, len(nodes) - 1}
        cuts.update(i for i, node in enumerate(nodes) if membership[node] > 1 or repeats[node] > 1)
        for i in range(len(nodes) - 1):
            if inside[nodes[i]] != inside[nodes[i + 1]]:
                cuts.update((i, i + 1))
        cuts = sorted(cuts)
        for start, end in zip(cuts, cuts[1:]):
            part = nodes[start:end + 1]
            geom = ogr.Geometry(ogr.wkbLineString)
            for node in part:
                geom.AddPoint_2D(*projected[node])
            if geom.Length() <= 0:
                counts["excluded_zero_length_segments"] += 1
                continue
            # Keep original OSM node IDs; do not invent boundary-cut nodes.
            if not all(inside[n] for n in part) or not area.Contains(geom):
                counts["excluded_boundary_or_outside_segments"] += 1
                continue
            coords = [projected[node] for node in part]
            candidates = []
            if travel != "reverse":
                candidates.append((part[0], part[-1], coords, False))
            if travel != "forward":
                candidates.append((part[-1], part[0], list(reversed(coords)), True))
            for u, v, coordinates, reversed_ in candidates:
                for node in (u, v):
                    graph.add_node(node, x=projected[node][0], y=projected[node][1], lon=points[node][0], lat=points[node][1])
                edge_geom = ogr.Geometry(ogr.wkbLineString)
                for xy in coordinates:
                    edge_geom.AddPoint_2D(*xy)
                attrs = dict(osm_way_id=int(way["id"]), segment_index=start, length_m=geom.Length(),
                    highway=str(tags["highway"]), oneway="no" if travel == "both" else "yes",
                    name=tags.get("name", ""), reversed=reversed_, osm_tags_json=json.dumps(tags, ensure_ascii=False, sort_keys=True),
                    geometry_wkt=edge_geom.ExportToWkt())
                key = graph.add_edge(u, v, **attrs)
                records.append(dict(u=u, v=v, key=key, **attrs))
    counts["retained_nodes"] = graph.number_of_nodes()
    counts["retained_directed_edges"] = graph.number_of_edges()
    if not records:
        raise ValueError("No OSM edges inside study_area")
    return graph, records, dict(counts)


def sample_positions(geometry, spacing):
    coords = np.array(geometry.GetPoints())[:, :2]
    lengths = np.linalg.norm(np.diff(coords, axis=0), axis=1)
    cumulative = np.r_[0.0, np.cumsum(lengths)]
    count = max(1, int(math.ceil(cumulative[-1] / spacing)))
    distances = (np.arange(count) + 0.5) * cumulative[-1] / count
    segments = np.minimum(np.searchsorted(cumulative, distances, side="right") - 1, len(lengths) - 1)
    ratios = (distances - cumulative[segments]) / lengths[segments]
    return coords[segments] + ratios[:, None] * (coords[segments + 1] - coords[segments])


def sample_array(array, positions, transform):
    inv = gdal.InvGeoTransform(transform)
    cols = np.floor(inv[0] + positions[:, 0] * inv[1] + positions[:, 1] * inv[2]).astype(int)
    rows = np.floor(inv[3] + positions[:, 0] * inv[4] + positions[:, 1] * inv[5]).astype(int)
    valid = (cols >= 0) & (rows >= 0) & (cols < array.shape[1]) & (rows < array.shape[0])
    values = np.full(len(positions), np.nan)
    values[valid] = array[rows[valid], cols[valid]]
    return values


def extract_features(geometry, arrays, transform, config, elev_bounds):
    positions = sample_positions(geometry, config["sample_spacing_m"])
    samples = {name: sample_array(array, positions, transform) for name, array in arrays.items()}
    samples["worldcover"][~np.isin(samples["worldcover"], WC_CLASSES)] = np.nan
    result = {field: None for field in FEATURE_FIELDS}
    result["sample_count"] = len(positions)
    flags = []
    for name, values in samples.items():
        good = values[np.isfinite(values)]
        fraction = len(good) / len(values)
        result[f"{name}_valid_frac"] = fraction
        if fraction < config["min_edge_coverage"]:
            flags.append(f"{name}_insufficient_coverage")
            continue
        if name == "dem":
            result.update(elev_mean_m=float(good.mean()), elev_min_m=float(good.min()))
            lo, hi = elev_bounds
            result["low_elev_norm"] = float(np.clip((hi - good.mean()) / (hi - lo), 0, 1)) if hi > lo else 0.5
        elif name == "slope":
            result.update(slope_mean_deg=float(good.mean()), slope_p90_deg=float(np.percentile(good, 90)))
            result["flatness_risk"] = float(np.clip(1 - good.mean() / config["flatness_zero_at_deg"], 0, 1))
        else:
            result.update(builtup_frac=float(np.mean(good == 50)),
                          vegetation_frac=float(np.mean(np.isin(good, config["vegetation_classes"]))),
                          water_frac=float(np.mean(good == 80)))
    result["quality_flag"] = ";".join(flags) if flags else "ok"
    return result


def write_edges(path, records, audit_ids):
    if path.exists():
        path.unlink()
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    for layer_name, selected in (("road_static_features", records), ("audit_20_edges", [r for r in records if (r["u"], r["v"], r["key"]) in audit_ids])):
        layer = ds.CreateLayer(layer_name, spatial_ref(COMPUTE_CRS), ogr.wkbLineString)
        for names, kind in ((INT_FIELDS, ogr.OFTInteger64), (FLOAT_FIELDS, ogr.OFTReal), (TEXT_FIELDS, ogr.OFTString)):
            for name in names:
                layer.CreateField(ogr.FieldDefn(name, kind))
        ds.StartTransaction()
        for record in selected:
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetGeometry(ogr.CreateGeometryFromWkt(record["geometry_wkt"]))
            for name in REQUIRED_FIELDS:
                if record.get(name) is not None:
                    feature.SetField(name, record[name])
            if layer.CreateFeature(feature) != 0:
                raise RuntimeError("Failed to write edge")
        ds.CommitTransaction()
        ds.ExecuteSQL(f'CREATE UNIQUE INDEX "{layer_name}_edge_id" ON "{layer_name}" (u,v,"key")')
    ds = None


def load_feature_graph(path):
    ds = ogr.Open(str(path))
    if ds is None:
        raise ValueError(f"Cannot open {path}")
    layer = ds.GetLayerByName("road_static_features")
    if layer is None or layer.GetSpatialRef().GetAuthorityCode(None) != "32650":
        raise ValueError("A -> B layer/CRS mismatch")
    names = {f.GetName() for f in layer.schema}
    if not set(REQUIRED_FIELDS).issubset(names):
        raise ValueError(f"Missing fields: {set(REQUIRED_FIELDS) - names}")
    graph = nx.MultiDiGraph(crs=COMPUTE_CRS)
    for feature in layer:
        attrs = {name: feature.GetField(name) for name in REQUIRED_FIELDS}
        u, v, key = (attrs.pop(name) for name in ("u", "v", "key"))
        if attrs["schema_version"] != SCHEMA_VERSION or graph.has_edge(u, v, key):
            raise ValueError("Version mismatch or duplicate (u,v,key)")
        geom = feature.GetGeometryRef()
        for node, xy in ((u, geom.GetPoint_2D(0)), (v, geom.GetPoint_2D(geom.GetPointCount() - 1))):
            if node in graph and math.dist((graph.nodes[node]["x"], graph.nodes[node]["y"]), xy) > 0.01:
                raise ValueError("OSM node has inconsistent coordinates")
            graph.add_node(node, x=xy[0], y=xy[1])
        attrs["geometry_wkt"] = geom.ExportToWkt()
        graph.add_edge(u, v, key=key, **attrs)
    ds = None
    return graph


def validate_output(out, source_graph, grids, config):
    graph = load_feature_graph(out / "road_static_features.gpkg")
    errors = []
    if set(graph.edges(keys=True)) != set(source_graph.edges(keys=True)):
        errors.append("GraphML/GeoPackage edge IDs differ")
    valid = 0
    missing = Counter()
    values = defaultdict(list)
    max_length_error = 0.0
    for u, v, key, data in graph.edges(keys=True, data=True):
        geom = ogr.CreateGeometryFromWkt(data["geometry_wkt"])
        max_length_error = max(max_length_error, abs(geom.Length() - data["length_m"]))
        source = source_graph[u][v][key]
        if data["osm_way_id"] != source["osm_way_id"] or data["geometry_wkt"] != source["geometry_wkt"]:
            errors.append(f"OSM provenance/geometry mismatch {(u,v,key)}")
        if geom.Length() <= 0 or not geom.IsValid():
            errors.append(f"Invalid geometry {(u,v,key)}")
        valid += all(data[field] is not None for field in FEATURE_FIELDS)
        for field in FEATURE_FIELDS:
            if data[field] is None:
                missing[field] += 1
            elif not math.isfinite(data[field]):
                errors.append(f"Nonfinite feature {field}")
            else:
                values[field].append(data[field])
        for field in NORMALIZED_FIELDS:
            if data[field] is not None and not 0 <= data[field] <= 1:
                errors.append(f"Out-of-range {field}")
    total = graph.number_of_edges()
    if max_length_error > 0.01:
        errors.append("length_m differs from projected geometry length")
    if total == 0 or valid / total < config["min_valid_edge_fraction"]:
        errors.append("Fewer than 90% of edges have valid features")
    digest = hashlib.sha256()
    for u, v, key in sorted(graph.edges(keys=True)):
        digest.update(json.dumps([u, v, key, graph[u][v][key]], sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return dict(passed=not errors, errors=errors[:30], directed=True, multigraph=True,
        edge_count=total, node_count=graph.number_of_nodes(), complete_feature_edges=valid,
        complete_feature_fraction=valid / total if total else 0,
        max_length_error_m=max_length_error, missing_by_field=dict(missing),
        grids=grids, distributions={k: dict(min=float(min(v)), mean=float(np.mean(v)), max=float(max(v))) for k, v in values.items()},
        semantic_sha256=digest.hexdigest())


def build(root, config_path, output=None):
    gdal.UseExceptions()
    ogr.UseExceptions()
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if config["crs"] != COMPUTE_CRS or config["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported schema/CRS")
    if config["resolution_m"] != 30 or config["sample_spacing_m"] <= 0 or config["flatness_zero_at_deg"] <= 0:
        raise ValueError("Invalid raster/sampling configuration")
    out = output or root / config["output_dir"]
    out.mkdir(parents=True, exist_ok=True)
    area, area_metadata = read_area(root / config["study_area"])
    inputs = [root / config["study_area"], root / config["osm"], *sorted(root.glob(config["dem_glob"])), *sorted(root.glob(config["worldcover_glob"]))]
    sources = {str(p.relative_to(root)).replace("\\", "/"): dict(bytes=p.stat().st_size, sha256=sha256(p)) for p in inputs}
    version_hash = hashlib.sha256(json.dumps(dict(sources=sources, config=config), sort_keys=True).encode()).hexdigest()[:16]
    source_version = f"gis-v{SCHEMA_VERSION}-{version_hash}"
    print("Building projected 30m raster grid", flush=True)
    arrays, grids = build_rasters(root, config, out, area)
    elevations = arrays["dem"][np.isfinite(arrays["dem"])]
    if not len(elevations):
        raise ValueError("DEM has no valid pixels")
    elev_bounds = np.percentile(elevations, config["elevation_percentiles"]).tolist()
    print("Building directed OSM multigraph", flush=True)
    raw = json.loads((root / config["osm"]).read_text(encoding="utf-8"))
    graph, records, topology_counts = build_osm_graph(raw, area)
    graph.graph.update(source_version=source_version)
    nx.write_graphml(graph, out / "roads.graphml", infer_numeric_types=True)
    print(f"Sampling {len(records)} directed edges", flush=True)
    cache = {}
    for record in records:
        identity = (record["osm_way_id"], record["segment_index"])
        if identity not in cache:
            cache[identity] = extract_features(ogr.CreateGeometryFromWkt(record["geometry_wkt"]), arrays, grids["dem"]["transform"], config, elev_bounds)
        record.update(cache[identity], source_version=source_version, schema_version=SCHEMA_VERSION)
    # Draw unique physical segments so reverse edges do not duplicate the audit.
    representatives = {}
    for record in records:
        representatives.setdefault((record["osm_way_id"], record["segment_index"]), record)
    pool = list(representatives.values())
    rng = np.random.default_rng(config["audit_seed"])
    chosen = rng.choice(len(pool), size=min(config["audit_count"], len(pool)), replace=False)
    audit_ids = {(pool[i]["u"], pool[i]["v"], pool[i]["key"]) for i in chosen}
    write_edges(out / "road_static_features.gpkg", records, audit_ids)
    report = validate_output(out, graph, grids, config)
    report.update(schema_version=SCHEMA_VERSION, source_version=source_version, topology=topology_counts,
        audit_edge_ids=[list(e) for e in sorted(audit_ids)], manual_map_review="pending",
        normalization=dict(elevation_bounds_m=elev_bounds, flatness_zero_at_deg=config["flatness_zero_at_deg"]))
    write_json(out / "quality_report.json", report)
    write_json(out / "manifest.json", dict(schema_version=SCHEMA_VERSION, source_version=source_version,
        sources=sources, config=config, study_area=area_metadata, software=dict(gdal=gdal.VersionInfo(), numpy=np.__version__, networkx=nx.__version__),
        normalization=report["normalization"], grids=grids))
    print(json.dumps({k: report[k] for k in ("passed", "edge_count", "node_count", "complete_feature_fraction", "semantic_sha256")}), flush=True)
    if not report["passed"]:
        raise RuntimeError(f"A -> B validation failed: {report['errors']}")
    return report
