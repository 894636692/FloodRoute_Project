import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import ab_runtime
from qgis.core import QgsApplication, QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsProject
from floodroute.gis.station_match import StationMatcher
from floodroute.gis.static_features import write_json

app = QgsApplication([], False)
app.initQgis()
out = ab_runtime.ROOT / "data/derived/static"
matcher = StationMatcher(out / "road_static_features.gpkg")
feature = next(matcher.layer.getFeatures())
point = feature.geometry().interpolate(feature.geometry().length() * 0.5).asPoint()
transform = QgsCoordinateTransform(matcher.layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
lonlat = transform.transform(point)
nearest = matcher.match(lonlat.x(), lonlat.y(), radius_m=20, nearest_only=True)
assert any((m["u"], m["v"], m["key"]) == (feature["u"], feature["v"], feature["key"]) for m in nearest)
assert max(m["distance_m"] for m in nearest) < 0.001
assert matcher.match(0, 0, radius_m=20) == []
write_json(out / "station_match_test.json", dict(passed=True, synthetic_point_on_real_road=True,
    note="Synthetic verification point; no real station locations supplied", nearest=nearest))
print("Station matching passed: exact road hit, keyed ties, distant point produces no match")
del matcher
app.exitQgis()
