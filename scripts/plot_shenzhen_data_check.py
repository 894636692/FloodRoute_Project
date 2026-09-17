"""Create a quick overlay plot for the prepared Shenzhen dataset."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import rasterio
from rasterio.plot import show


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed" / "shenzhen_core"
OUT_PATH = DATA_DIR / "shenzhen_data_check.png"


def main() -> None:
    edges = gpd.read_file(DATA_DIR / "osm_edges_utm.geojson")

    fig, axes = plt.subplots(1, 2, figsize=(12, 6), dpi=150)

    with rasterio.open(DATA_DIR / "dem_utm_30m.tif") as dem:
        show(dem, ax=axes[0], cmap="terrain", title="DEM + OSM roads")
    edges.plot(ax=axes[0], color="black", linewidth=0.35, alpha=0.8)

    with rasterio.open(DATA_DIR / "worldcover_utm_30m_match_dem.tif") as wc:
        show(wc, ax=axes[1], cmap="tab20", title="WorldCover + OSM roads")
    edges.plot(ax=axes[1], color="black", linewidth=0.35, alpha=0.8)

    for ax in axes:
        ax.set_axis_off()
        ax.set_aspect("equal")

    fig.tight_layout()
    fig.savefig(OUT_PATH)
    plt.close(fig)
    print(f"saved: {OUT_PATH}")


if __name__ == "__main__":
    main()
