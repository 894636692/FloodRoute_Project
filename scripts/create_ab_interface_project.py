"""Create the review project and map sheets for the fixed 20-edge sample."""
from pathlib import Path
import os
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qgis.PyQt.QtCore import QSize, QRectF
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsLineSymbol, QgsProject,
    QgsRasterLayer, QgsVectorLayer, QgsReferencedRectangle, QgsRectangle,
    QgsMapSettings, QgsMapRendererParallelJob, QgsColorRampShader,
    QgsRasterShader, QgsSingleBandPseudoColorRenderer,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "data/derived/static"
CRS = QgsCoordinateReferenceSystem("EPSG:32650")
WC_COLORS = {10: "#006400", 20: "#ffbb22", 30: "#ffff4c", 40: "#f096ff",
             50: "#fa0000", 60: "#b4b4b4", 70: "#f0f0f0", 80: "#0064c8",
             90: "#0096a0", 95: "#00cf75", 100: "#fae6a0"}


def render(layers, extent, width, height):
    settings = QgsMapSettings()
    settings.setDestinationCrs(CRS)
    settings.setLayers(layers)
    settings.setExtent(extent)
    settings.setOutputSize(QSize(width, height))
    settings.setBackgroundColor(QColor("white"))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    return job.renderedImage()


def color_raster(layer, stops, discrete=False):
    ramp = QgsColorRampShader()
    ramp.setColorRampType(QgsColorRampShader.Exact if discrete else QgsColorRampShader.Interpolated)
    ramp.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, QColor(c), str(v)) for v, c in stops])
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(ramp)
    layer.setRenderer(QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader))


def main():
    app = QgsApplication([], False)
    app.initQgis()
    project = QgsProject.instance()
    project.clear()
    project.setCrs(CRS)
    dem = QgsRasterLayer(str(STATIC / "dem_30m.tif"), "高程 DEM（米）")
    cover = QgsRasterLayer(str(STATIC / "worldcover_30m.tif"), "土地覆盖 WorldCover")
    slope = QgsRasterLayer(str(STATIC / "slope_deg.tif"), "坡度（度）")
    roads = QgsVectorLayer(str(STATIC / "road_static_features.gpkg") + "|layername=road_static_features", "道路静态特征 A→B v1", "ogr")
    audit = QgsVectorLayer(str(STATIC / "road_static_features.gpkg") + "|layername=audit_20_edges", "空间抽查：20 条道路", "ogr")
    layers = [dem, cover, slope, roads, audit]
    for layer in layers:
        if not layer.isValid():
            raise RuntimeError(layer.source())
        project.addMapLayer(layer)
    color_raster(dem, [(-15, "#e5f5f9"), (0, "#f7fcfd"), (30, "#ccece6"), (100, "#66c2a4"), (250, "#238b45"), (500, "#00441b")])
    color_raster(cover, sorted(WC_COLORS.items()), discrete=True)
    roads.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "#555555", "width": "0.16"}))
    audit.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "#ff00dc", "width": "1.0"}))
    for layer in (cover, slope):
        project.layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(False)
    extent = roads.extent()
    extent.scale(1.05)
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, CRS))
    project.writeEntry("FloodRoute", "schema_version", "1.0.0")
    route_path = STATIC / "b_baseline_route.geojson"
    if route_path.exists():
        route = QgsVectorLayer(str(route_path), "B端接口验收：最短路线", "ogr")
        if not route.isValid():
            raise RuntimeError(route.source())
        route.renderer().setSymbol(QgsLineSymbol.createSimple({"color": "#1a4dff", "width": "0.85"}))
        project.addMapLayer(route)
    path = STATIC / "a_to_b_interface_review.qgz"
    if not project.write(str(path)):
        raise RuntimeError("Cannot save QGIS project")
    overview_layers = ([route] if route_path.exists() else []) + [audit, roads, dem]
    render(overview_layers, extent, 1500, 1000).save(str(STATIC / "interface_overview.png"))
    features = list(audit.getFeatures())
    for page in range(4):
        canvas = QImage(1600, 1500, QImage.Format_ARGB32)
        canvas.fill(QColor("white"))
        painter = QPainter(canvas)
        painter.setFont(QFont("Microsoft YaHei", 10))
        for row, feature in enumerate(features[page * 5:page * 5 + 5]):
            audit.setSubsetString(f'"fid" = {feature.id()}')
            box = feature.geometry().boundingBox()
            center = box.center()
            size = max(box.width(), box.height(), 180) * 1.5
            box = QgsRectangle(center.x() - size, center.y() - size / 2,
                               center.x() + size, center.y() + size / 2)
            title = f"{page * 5 + row + 1:02d}  ({feature['u']}, {feature['v']}, {feature['key']})  {feature['highway']}"
            painter.setPen(QColor("#111111"))
            painter.drawText(QRectF(10, row * 300, 1580, 25), title)
            for col, raster in enumerate((dem, cover)):
                painter.drawImage(col * 800, row * 300 + 28, render([audit, raster], box, 790, 225))
            values = {k: str(feature[k]) for k in ("elev_mean_m", "elev_min_m", "slope_mean_deg", "builtup_frac", "vegetation_frac", "water_frac")}
            label = " | ".join(f"{k}={v[:8]}" for k, v in values.items())
            painter.drawText(QRectF(10, row * 300 + 258, 1580, 36), label)
        painter.end()
        canvas.save(str(STATIC / f"audit_sheet_{page + 1}.png"))
    audit.setSubsetString("")
    # Reopen the saved project to verify relative layer paths and default extent.
    project.clear()
    if not project.read(str(path)) or not all(layer.isValid() for layer in project.mapLayers().values()):
        raise RuntimeError("Saved review project cannot be reopened")
    print(json.dumps({"project": str(path), "layers": len(project.mapLayers()), "audit_maps": 20}))
    project.clear()
    app.exitQgis()


if __name__ == "__main__":
    main()
