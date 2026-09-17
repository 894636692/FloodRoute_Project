from pathlib import Path
from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsFillSymbol, QgsLineSymbol, QgsProject, QgsRasterLayer, QgsSingleSymbolRenderer, QgsVectorLayer

root = Path(r'D:\LaotuZhBi\laotu-data')
static = root / 'data' / 'processed' / 'static_risk'
project_path = static / 'static_risk_visible_project.qgz'
qgs = QgsApplication([], False)
qgs.initQgis()
project = QgsProject.instance()
project.clear()
project.setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))

risk = QgsRasterLayer(str(static / 'static_risk_rgb_visible.tif'), '静态风险彩色图 Green-Yellow-Red')
roads = QgsVectorLayer(str(static / 'static_risk_layers.gpkg') + '|layername=roads_static_risk', '道路静态风险 risk_mean/risk_max/risk_p90', 'ogr')
bbox = QgsVectorLayer(str(static / 'study_area_bbox.geojson'), '研究区范围 bbox', 'ogr')
for layer in [risk, roads, bbox]:
    if not layer.isValid():
        raise RuntimeError(f'Invalid layer: {layer.name()} {layer.source()}')
    project.addMapLayer(layer)

roads.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({'color': '#0033ff', 'width': '0.65'})))
roads.setOpacity(0.85)
bbox_symbol = QgsFillSymbol.createSimple({'color': '255,255,255,0', 'outline_color': '#000000', 'outline_width': '0.8'})
bbox.setRenderer(QgsSingleSymbolRenderer(bbox_symbol))
if not project.write(str(project_path)):
    raise RuntimeError('Failed to write project')
print(project_path)
qgs.exitQgis()
