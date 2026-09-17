"""Step 4: download real OSM driving roads and draw the shared test area."""

import json
import os
from pathlib import Path

project_dir = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(project_dir / "work" / "matplotlib"))

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")  # Save a PNG without opening a separate plot window.
import matplotlib.pyplot as plt
import osmnx as ox
from pyproj import CRS

# 1. Read the ONE shared boundary. Each GeoDataFrame row is one feature.
area = gpd.read_file(project_dir / "study_area.geojson")
assert len(area) == 1 and area.geometry.is_valid.all()
assert area.crs is not None and area.crs.to_epsg() == 4326
polygon = area.geometry.iloc[0]
print("Study area CRS:", area.crs, flush=True)
print("Study area bbox [west, south, east, north]:", area.total_bounds, flush=True)

raw_dir = project_dir / "data" / "raw" / "osm"
processed_dir = project_dir / "data" / "processed" / "osm"
maps_dir = project_dir / "outputs" / "maps"
for directory in [raw_dir, processed_dir, maps_dir]:
    directory.mkdir(parents=True, exist_ok=True)

# 2. Cache unmodified API responses separately from processed graph data.
ox.settings.use_cache = True
ox.settings.cache_folder = raw_dir / "api_cache"
ox.settings.log_console = True
ox.settings.requests_timeout = 180
print("OSMnx version:", ox.__version__, flush=True)
print("Overpass service:", ox.settings.overpass_url, flush=True)
print("Downloading driving roads. The server may queue this request.", flush=True)

# OSMnx internally projects/buffers the query by a small margin for topology.
# Input/output coordinates remain EPSG:4326; final linework is clipped below.
G = ox.graph_from_polygon(
    polygon,
    network_type="drive",
    simplify=True,
    retain_all=True,
    truncate_by_edge=True,
)
assert G.number_of_edges() > 0, "No driving roads returned for this area"
assert CRS.from_user_input(G.graph["crs"]) == area.crs

# 3. Graph nodes are junctions/endpoints; each directed edge is one road link.
nodes, edges = ox.graph_to_gdfs(G)
print("\n--- Road network checks ---")
print("Nodes:", G.number_of_nodes())
print("Directed edges:", G.number_of_edges())
print("Graph CRS:", G.graph["crs"])
print("Node table shape:", nodes.shape)
print("Edge table shape:", edges.shape)
assert edges.crs == area.crs
assert edges.geometry.is_valid.all()
assert edges["length"].notna().all() and (edges["length"] >= 0).all()
print("Highway types (a list means merged OSM segments):")
print(edges["highway"].astype(str).value_counts().to_string())
print("Original edge length statistics (metres):")
print(edges["length"].describe().to_string())
print("Sample edge attributes:")
print(edges[["highway", "length"]].head().to_string())

# GraphML preserves graph connectivity, direction and full edge attributes.
graph_path = processed_dir / "network.graphml"
ox.save_graphml(G, graph_path)
restored = ox.load_graphml(graph_path)
assert restored.number_of_nodes() == G.number_of_nodes()
assert restored.number_of_edges() == G.number_of_edges()

# 4. Clip road geometry to the shared polygon, without changing the CRS.
# This creates a display layer, not a new routable graph.
roads = gpd.clip(edges.reset_index(), area, keep_geom_type=True)
roads = roads.loc[~roads.geometry.is_empty].copy()
assert not roads.empty and roads.geometry.is_valid.all()
assert roads.geom_type.isin(["LineString", "MultiLineString"]).all()
columns = ["u", "v", "key", "osmid", "highway", "name", "oneway", "length", "geometry"]
roads = roads[[column for column in columns if column in roads.columns]].copy()
# Original length belongs to the WHOLE graph edge, not its clipped fragment.
roads = roads.rename(columns={"length": "length_original_m"})

# Simplified edges may have list-valued attributes. Encode them for GIS readers.
for column in roads.columns:
    if column != "geometry":
        roads[column] = roads[column].map(
            lambda value: json.dumps(value, ensure_ascii=False)
            if isinstance(value, (list, tuple, dict)) else value
        )
roads_path = processed_dir / "roads.geojson"
roads.to_file(roads_path, driver="GeoJSON", index=False)
saved_roads = gpd.read_file(roads_path)
assert len(saved_roads) == len(roads) and saved_roads.crs == area.crs
print("Clipped road features:", len(saved_roads))
print("Clipped road CRS:", saved_roads.crs)

# 5. Plot the saved road layer and study boundary, both in EPSG:4326.
fig, ax = plt.subplots(figsize=(9, 9))
saved_roads.plot(ax=ax, color="#285d89", linewidth=0.65)
area.boundary.plot(ax=ax, color="#d1493f", linewidth=1.4)
ax.set_title("Shenzhen Futian test area - OSM driving roads")
ax.set_xlabel("Longitude (degrees; WGS 84)")
ax.set_ylabel("Latitude (degrees; WGS 84)")
ax.ticklabel_format(useOffset=False, style="plain")
ax.grid(alpha=0.2)
fig.text(0.5, 0.015, "Red: test boundary | Blue: roads | Data: (c) OpenStreetMap contributors, ODbL", ha="center", fontsize=8)
fig.tight_layout(rect=(0, 0.035, 1, 1))
map_path = maps_dir / "osm_roads_test.png"
fig.savefig(map_path, dpi=200)
plt.close(fig)
print("\nGraph saved:", graph_path)
print("Roads saved:", roads_path)
print("Map saved:", map_path)
print("OSM checks passed. Please inspect the PNG before the next step.")
