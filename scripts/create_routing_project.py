from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsMarkerSymbol,
    QgsProject,
    QgsRasterLayer,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsLineSymbol,
)


ROOT = Path(r"D:\LaotuZhBi\laotu-data")
STATIC = ROOT / "data" / "processed" / "static_risk"
ROUTING = STATIC / "routing"
PROJECT_PATH = ROUTING / "routing_project.qgz"


def line_symbol(color: str, width: str) -> QgsLineSymbol:
    return QgsLineSymbol.createSimple({"color": color, "width": width})


def main() -> None:
    qgs = QgsApplication([], False)
    qgs.initQgis()
    project = QgsProject.instance()
    project.clear()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

    risk = QgsRasterLayer(
        str(STATIC / "static_risk_rgb_visible.tif"),
        "静态风险背景 Green-Yellow-Red",
    )
    roads = QgsVectorLayer(
        str(STATIC / "static_risk_layers.gpkg") + "|layername=roads_static_risk",
        "道路网络（浅灰）",
        "ogr",
    )
    routes = QgsVectorLayer(
        str(ROUTING / "routing_results.gpkg") + "|layername=routes_comparison",
        "规划路线对比",
        "ogr",
    )
    endpoints = QgsVectorLayer(
        str(ROUTING / "routing_results.gpkg") + "|layername=route_endpoints",
        "起点与终点",
        "ogr",
    )
    layers = [risk, roads, routes, endpoints]
    for layer in layers:
        if not layer.isValid():
            raise RuntimeError(f"Invalid layer: {layer.name()} -> {layer.source()}")
        project.addMapLayer(layer, False)

    risk.setOpacity(0.88)
    roads.setRenderer(QgsSingleSymbolRenderer(line_symbol("#666666", "0.35")))
    roads.setOpacity(0.28)

    categories = [
        QgsRendererCategory(
            "shortest_route",
            line_symbol("#111111", "1.55"),
            "最短路线",
        ),
        QgsRendererCategory(
            "risk_aware_route",
            line_symbol("#00e5ff", "2.00"),
            "风险感知路线",
        ),
    ]
    routes.setRenderer(QgsCategorizedSymbolRenderer("route_type", categories))

    start_symbol = QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#00a651", "outline_color": "#ffffff", "size": "4.2"}
    )
    end_symbol = QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#d7191c", "outline_color": "#ffffff", "size": "4.2"}
    )
    endpoint_categories = [
        QgsRendererCategory("start", start_symbol, "起点"),
        QgsRendererCategory("end", end_symbol, "终点"),
    ]
    endpoints.setRenderer(QgsCategorizedSymbolRenderer("role", endpoint_categories))

    root = project.layerTreeRoot()
    root.addLayer(risk)
    root.addLayer(roads)
    root.addLayer(routes)
    root.addLayer(endpoints)

    if not project.write(str(PROJECT_PATH)):
        raise RuntimeError(f"Failed to write project: {PROJECT_PATH}")
    print(PROJECT_PATH)
    qgs.exitQgis()


if __name__ == "__main__":
    main()
