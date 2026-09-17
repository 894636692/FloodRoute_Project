from __future__ import annotations

from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsProject,
    QgsRasterLayer,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)


ROOT = Path(r"D:\LaotuZhBi\laotu-data")
DYNAMIC = ROOT / "data" / "processed" / "dynamic_risk"
STATIC = ROOT / "data" / "processed" / "static_risk"
ROUTING = DYNAMIC / "routing"
PROJECT_PATH = ROUTING / "dynamic_routing_project.qgz"


def line(color: str, width: str, style: str = "solid") -> QgsLineSymbol:
    props = {"color": color, "width": width}
    if style != "solid":
        props["line_style"] = style
    return QgsLineSymbol.createSimple(props)


def main() -> None:
    qgs = QgsApplication([], False)
    qgs.initQgis()
    project = QgsProject.instance()
    project.clear()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

    dynamic_bg = QgsRasterLayer(
        str(DYNAMIC / "dynamic_risk_stress_30mm_stress_30mm_per_h_rgb.tif"),
        "动态风险背景：30mm/h压力测试",
    )
    static_bg = QgsRasterLayer(str(STATIC / "static_risk_rgb_visible.tif"), "静态风险背景")
    roads = QgsVectorLayer(
        str(STATIC / "static_risk_layers.gpkg") + "|layername=roads_static_risk",
        "道路网络（灰色）",
        "ogr",
    )
    routes = QgsVectorLayer(
        str(ROUTING / "dynamic_routing_results.gpkg") + "|layername=routes_dynamic_comparison",
        "动态路线对比",
        "ogr",
    )
    endpoints = QgsVectorLayer(
        str(ROUTING / "dynamic_routing_results.gpkg") + "|layername=route_endpoints",
        "起点与终点",
        "ogr",
    )

    for layer in [static_bg, dynamic_bg, roads, routes, endpoints]:
        if not layer.isValid():
            raise RuntimeError(f"Invalid layer: {layer.name()} -> {layer.source()}")
        project.addMapLayer(layer, False)

    static_bg.setOpacity(0.0)
    dynamic_bg.setOpacity(0.9)
    roads.setRenderer(QgsSingleSymbolRenderer(line("#666666", "0.30")))
    roads.setOpacity(0.22)

    # Same route_type appears in two scenarios. Use combined scenario+route label
    # via duplicated route_type colors that still make interpretation simple.
    categories = [
        QgsRendererCategory("shortest_route", line("#111111", "1.25", "dash"), "最短路线"),
        QgsRendererCategory("dynamic_risk_route", line("#00e5ff", "2.10"), "动态风险路线"),
    ]
    routes.setRenderer(QgsCategorizedSymbolRenderer("route_type", categories))

    start_symbol = QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#00a651", "outline_color": "#ffffff", "size": "4.2"}
    )
    end_symbol = QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#d7191c", "outline_color": "#ffffff", "size": "4.2"}
    )
    endpoints.setRenderer(
        QgsCategorizedSymbolRenderer(
            "role",
            [
                QgsRendererCategory("start", start_symbol, "起点"),
                QgsRendererCategory("end", end_symbol, "终点"),
            ],
        )
    )

    root = project.layerTreeRoot()
    for layer in [static_bg, dynamic_bg, roads, routes, endpoints]:
        node = root.addLayer(layer)
        if layer.name() == "静态风险背景":
            node.setItemVisibilityChecked(False)

    if not project.write(str(PROJECT_PATH)):
        raise RuntimeError(f"Failed to write project: {PROJECT_PATH}")
    print(PROJECT_PATH)
    qgs.exitQgis()


if __name__ == "__main__":
    main()
