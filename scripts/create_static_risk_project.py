from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsColorRampShader,
    QgsFillSymbol,
    QgsGraduatedSymbolRenderer,
    QgsLineSymbol,
    QgsMapLayerType,
    QgsProject,
    QgsRasterLayer,
    QgsRasterShader,
    QgsRendererRange,
    QgsSingleBandPseudoColorRenderer,
    QgsVectorLayer,
)


ROOT = Path(r"D:\LaotuZhBi\laotu-data")
STATIC = ROOT / "data" / "processed" / "static_risk"
PROJECT_PATH = STATIC / "static_risk_project.qgz"


def style_risk_raster(layer: QgsRasterLayer) -> None:
    shader = QgsRasterShader()
    ramp = QgsColorRampShader()
    ramp.setColorRampType(QgsColorRampShader.Interpolated)
    ramp.setColorRampItemList(
        [
            QgsColorRampShader.ColorRampItem(0.0, QColor("#1a9850"), "Low"),
            QgsColorRampShader.ColorRampItem(0.5, QColor("#ffffbf"), "Medium"),
            QgsColorRampShader.ColorRampItem(1.0, QColor("#d73027"), "High"),
        ]
    )
    shader.setRasterShaderFunction(ramp)
    layer.setRenderer(QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader))
    layer.setOpacity(0.72)
    layer.triggerRepaint()


def style_roads(layer: QgsVectorLayer) -> None:
    ranges = []
    colors = ["#1a9850", "#91cf60", "#ffffbf", "#fc8d59", "#d73027"]
    bounds = [(0.0, 0.2, "0.0-0.2"), (0.2, 0.4, "0.2-0.4"), (0.4, 0.6, "0.4-0.6"), (0.6, 0.8, "0.6-0.8"), (0.8, 1.01, "0.8-1.0")]
    for (lower, upper, label), color in zip(bounds, colors):
        symbol = QgsLineSymbol.createSimple({"color": color, "width": "0.45"})
        ranges.append(QgsRendererRange(lower, upper, symbol, label))
    renderer = QgsGraduatedSymbolRenderer("risk_mean", ranges)
    renderer.setMode(QgsGraduatedSymbolRenderer.Custom)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


def style_worldcover(layer: QgsRasterLayer) -> None:
    # Keep WorldCover subdued below risk layers.
    layer.setOpacity(0.45)
    layer.triggerRepaint()


def main() -> None:
    qgs = QgsApplication([], False)
    qgs.initQgis()
    project = QgsProject.instance()
    project.clear()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

    layers = [
        QgsRasterLayer(str(STATIC / "dem_clip.tif"), "DEM clip"),
        QgsRasterLayer(str(STATIC / "worldcover_clip_30m.tif"), "WorldCover 30m"),
        QgsRasterLayer(str(STATIC / "risk_elevation.tif"), "Risk elevation"),
        QgsRasterLayer(str(STATIC / "risk_slope.tif"), "Risk slope"),
        QgsRasterLayer(str(STATIC / "risk_landcover.tif"), "Risk landcover"),
        QgsRasterLayer(str(STATIC / "static_risk.tif"), "Static risk 0-1"),
        QgsVectorLayer(
            str(STATIC / "static_risk_layers.gpkg") + "|layername=roads_static_risk",
            "Roads static risk",
            "ogr",
        ),
    ]

    for layer in layers:
        if not layer.isValid():
            raise RuntimeError(f"Invalid layer: {layer.name()} -> {layer.source()}")
        project.addMapLayer(layer)

    for layer in project.mapLayers().values():
        if layer.type() == QgsMapLayerType.RasterLayer and layer.name().startswith("Risk"):
            style_risk_raster(layer)
        elif layer.type() == QgsMapLayerType.RasterLayer and layer.name() == "Static risk 0-1":
            style_risk_raster(layer)
        elif layer.type() == QgsMapLayerType.RasterLayer and layer.name() == "WorldCover 30m":
            style_worldcover(layer)
        elif layer.type() == QgsMapLayerType.VectorLayer and layer.name() == "Roads static risk":
            style_roads(layer)

    root = project.layerTreeRoot()
    for child in root.children():
        layer = child.layer()
        if layer and layer.name() in {"Risk elevation", "Risk slope", "Risk landcover"}:
            child.setItemVisibilityChecked(False)
        if layer and layer.name() == "DEM clip":
            child.setItemVisibilityChecked(False)

    if not project.write(str(PROJECT_PATH)):
        raise RuntimeError(f"Failed to write project: {PROJECT_PATH}")
    print(PROJECT_PATH)
    qgs.exitQgis()


if __name__ == "__main__":
    main()
