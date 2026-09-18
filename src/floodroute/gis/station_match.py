"""Station-to-edge matches in meters, preserving every directed (u,v,key)."""
import math
from qgis.core import (
    QgsVectorLayer, QgsSpatialIndex, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsProject, QgsGeometry, QgsPointXY, QgsRectangle,
)


class StationMatcher:
    def __init__(self, gpkg):
        self.layer = QgsVectorLayer(str(gpkg) + "|layername=road_static_features", "edges", "ogr")
        if not self.layer.isValid() or self.layer.crs().authid() != "EPSG:32650":
            raise ValueError("Expected valid EPSG:32650 A -> B road layer")
        self.index = QgsSpatialIndex(self.layer.getFeatures(), flags=QgsSpatialIndex.FlagStoreFeatureGeometries)
        self.transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"),
            self.layer.crs(), QgsProject.instance())

    def match(self, lon, lat, radius_m=250, nearest_only=False):
        if not math.isfinite(radius_m) or radius_m <= 0:
            raise ValueError("radius_m must be finite and positive")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("Invalid EPSG:4326 coordinate")
        point = self.transform.transform(QgsPointXY(lon, lat))
        geometry = QgsGeometry.fromPointXY(point)
        candidates = self.index.intersects(QgsRectangle(point.x() - radius_m, point.y() - radius_m,
            point.x() + radius_m, point.y() + radius_m))
        matches = []
        for fid in candidates:
            feature = self.layer.getFeature(fid)
            distance = feature.geometry().distance(geometry)
            if distance <= radius_m:
                matches.append(dict(u=int(feature["u"]), v=int(feature["v"]), key=int(feature["key"]), distance_m=distance))
        matches.sort(key=lambda r: (r["distance_m"], r["u"], r["v"], r["key"]))
        # Return both directions (and coincident parallel edges) on nearest-distance ties.
        if nearest_only and matches:
            matches = [r for r in matches if r["distance_m"] <= matches[0]["distance_m"] + 1e-6]
        return matches
