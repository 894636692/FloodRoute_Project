"""Download and prepare a small Shenzhen study area dataset.

Outputs:
- raw Copernicus DEM GLO-30 tile
- raw ESA WorldCover 2021 tile
- clipped WGS84 rasters for the same bbox
- aligned UTM Zone 50N rasters on the DEM 30m grid
- OSM drive road network for the same bbox

The selected area is intentionally small to keep download and processing fast.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
import rasterio
from rasterio.enums import Resampling
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject
import requests
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed" / "shenzhen_core"

# Small Shenzhen core area, roughly Futian / central urban district.
# bbox order: west, south, east, north in WGS84 lon/lat.
BBOX = (114.03, 22.50, 114.08, 22.55)
UTM_CRS = "EPSG:32650"

DEM_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N22_00_E114_00_DEM/"
    "Copernicus_DSM_COG_10_N22_00_E114_00_DEM.tif"
)
WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_N21E114_Map.tif"
)


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        print(f"skip existing: {path}")
        return

    print(f"download: {url}", flush=True)
    head = requests.head(url, allow_redirects=True, timeout=(15, 30))
    head.raise_for_status()
    total = int(head.headers.get("content-length", "0"))
    chunk_size = 4 * 1024 * 1024
    tmp_path = path.with_suffix(path.suffix + ".part")
    if tmp_path.exists():
        tmp_path.unlink()

    with tmp_path.open("wb") as file:
        if total <= 0:
            response = requests.get(url, timeout=(15, 60))
            response.raise_for_status()
            file.write(response.content)
        else:
            downloaded = 0
            while downloaded < total:
                end = min(downloaded + chunk_size - 1, total - 1)
                response = requests.get(
                    url,
                    headers={"Range": f"bytes={downloaded}-{end}"},
                    timeout=(15, 60),
                )
                response.raise_for_status()
                file.write(response.content)
                downloaded += len(response.content)
                percent = downloaded / total * 100
                print(f"  {path.name}: {percent:5.1f}%", flush=True)
                if not response.content:
                    raise RuntimeError(f"download stalled: {url}")

    tmp_path.replace(path)
    print(f"saved: {path} ({path.stat().st_size / 1024 / 1024:.1f} MB)")


def clip_to_bbox(src_path: Path, dst_path: Path, bbox: tuple[float, float, float, float]) -> None:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    west, south, east, north = bbox
    geometry = [box(west, south, east, north).__geo_interface__]

    with rasterio.open(src_path) as src:
        data, transform = mask(src, geometry, crop=True)
        profile = src.profile.copy()
        profile.update(
            height=data.shape[1],
            width=data.shape[2],
            transform=transform,
            compress="deflate",
            tiled=True,
        )
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(data)
    print(f"clipped: {dst_path}")


def reproject_dem_to_utm(src_path: Path, dst_path: Path, resolution: float = 30.0) -> dict:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs,
            UTM_CRS,
            src.width,
            src.height,
            *src.bounds,
            resolution=resolution,
        )
        profile = src.profile.copy()
        profile.update(
            crs=UTM_CRS,
            transform=transform,
            width=width,
            height=height,
            dtype="float32",
            nodata=-9999.0,
            compress="deflate",
            tiled=True,
        )
        with rasterio.open(dst_path, "w", **profile) as dst:
            reproject(
                source=rasterio.band(src, 1),
                destination=rasterio.band(dst, 1),
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=UTM_CRS,
                resampling=Resampling.bilinear,
                dst_nodata=-9999.0,
            )
    print(f"aligned DEM: {dst_path}")
    return {"crs": UTM_CRS, "transform": transform, "width": width, "height": height}


def reproject_to_match(
    src_path: Path,
    dst_path: Path,
    template: dict,
    resampling: Resampling,
    dtype: str,
    nodata: int | float,
) -> None:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(src_path) as src:
        profile = src.profile.copy()
        profile.update(
            crs=template["crs"],
            transform=template["transform"],
            width=template["width"],
            height=template["height"],
            dtype=dtype,
            nodata=nodata,
            compress="deflate",
            tiled=True,
        )
        with rasterio.open(dst_path, "w", **profile) as dst:
            reproject(
                source=rasterio.band(src, 1),
                destination=rasterio.band(dst, 1),
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=template["transform"],
                dst_crs=template["crs"],
                resampling=resampling,
                dst_nodata=nodata,
            )
    print(f"aligned raster: {dst_path}")


def download_osm_roads(bbox: tuple[float, float, float, float]) -> None:
    west, south, east, north = bbox
    print("download OSM drive network from Overpass")
    graph = ox.graph_from_bbox(
        (west, south, east, north),
        network_type="drive",
        simplify=True,
        retain_all=False,
        truncate_by_edge=True,
    )
    graph = ox.distance.add_edge_lengths(graph)
    nodes, edges = ox.graph_to_gdfs(graph)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nodes_wgs84 = OUT_DIR / "osm_nodes_wgs84.geojson"
    edges_wgs84 = OUT_DIR / "osm_edges_wgs84.geojson"
    nodes_utm = OUT_DIR / "osm_nodes_utm.geojson"
    edges_utm = OUT_DIR / "osm_edges_utm.geojson"

    nodes.to_file(nodes_wgs84, driver="GeoJSON")
    edges.to_file(edges_wgs84, driver="GeoJSON")
    nodes.to_crs(UTM_CRS).to_file(nodes_utm, driver="GeoJSON")
    edges.to_crs(UTM_CRS).to_file(edges_utm, driver="GeoJSON")
    ox.save_graphml(graph, filepath=OUT_DIR / "osm_drive.graphml")

    print(f"OSM nodes: {len(nodes)}, edges: {len(edges)}")
    print(f"saved: {edges_wgs84}")


def write_metadata() -> None:
    metadata = {
        "study_area": "Shenzhen core / Futian small bbox",
        "bbox_wgs84": {
            "west": BBOX[0],
            "south": BBOX[1],
            "east": BBOX[2],
            "north": BBOX[3],
        },
        "aligned_crs": UTM_CRS,
        "sources": {
            "dem": {
                "name": "Copernicus DEM GLO-30",
                "url": DEM_URL,
            },
            "worldcover": {
                "name": "ESA WorldCover 2021 v200",
                "url": WORLDCOVER_URL,
            },
            "osm": {
                "name": "OpenStreetMap drive network",
                "tool": "OSMnx / Overpass API",
            },
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    dem_raw = RAW_DIR / "copernicus_dem_glo30_N22E114.tif"
    worldcover_raw = RAW_DIR / "esa_worldcover_2021_N21E114.tif"

    download(DEM_URL, dem_raw)
    download(WORLDCOVER_URL, worldcover_raw)

    dem_clip = OUT_DIR / "dem_wgs84_clip.tif"
    worldcover_clip = OUT_DIR / "worldcover_wgs84_clip.tif"
    clip_to_bbox(dem_raw, dem_clip, BBOX)
    clip_to_bbox(worldcover_raw, worldcover_clip, BBOX)

    dem_utm = OUT_DIR / "dem_utm_30m.tif"
    template = reproject_dem_to_utm(dem_clip, dem_utm, resolution=30.0)
    reproject_to_match(
        worldcover_clip,
        OUT_DIR / "worldcover_utm_30m_match_dem.tif",
        template,
        Resampling.nearest,
        dtype="uint8",
        nodata=0,
    )

    download_osm_roads(BBOX)
    write_metadata()
    print(f"done: {OUT_DIR}")


if __name__ == "__main__":
    main()
