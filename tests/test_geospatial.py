"""Deterministic smoke tests: no network calls and no real radar solution required."""
import io
import json
import unittest
import zipfile
from xml.etree import ElementTree as ET

import folium
import environment_layers as env
import aviation_layers as aviation
import microsoft_buildings as microsoft
import numpy as np
from shapely.geometry import Polygon
from obstacles import _polygon_ray_indices


class GeospatialDataTests(unittest.TestCase):
    def test_height_units(self):
        self.assertEqual(env.numeric_height("10m"), 10.)
        self.assertAlmostEqual(env.numeric_height("100 ft"), 30.48)
        self.assertIsNone(env.numeric_height("unknown"))
        self.assertIsNone(env.numeric_height("-20"))
        self.assertIsNone(env.numeric_height("NaN"))

    def test_geojson_roundtrip_height_and_filter(self):
        data = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"kind": "Building", "name": "Tower A",
                                              "height_m": 42.5},
            "geometry": {"type": "Polygon", "coordinates": [[
                [14.0, 50.0], [14.0001, 50.0], [14.0001, 50.0001], [14.0, 50.0]
            ]]}}]}
        items = env.import_geojson(json.dumps(data))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["height_m"], 42.5)
        selected = env.selected(items, 50., 14., ["Building"], 40, 5, False)
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(env.selected(items, 50., 14., ["Building"], 50, 5, False)), 0)
        self.assertEqual(len(env.selected(items, 50., 14., ["Forest"], 0, 5, True)), 0)
        self.assertEqual(len(env.selected(items, 50., 14., ["Building"], 40, 5, False,
                                          query="unrelated")), 0)
        exported = json.loads(env.geojson_bytes(selected))
        self.assertEqual(exported["features"][0]["properties"]["height_m"], 42.5)

    def test_maps_and_exports(self):
        items = [{"kind":"Forest","name":"Test forest","coordinates":[
            [50., 14.], [50.001,14.], [50.001,14.001]],
            "height_m": None,"height_quality":"unknown","source":"test",
            "source_id":"1","distance_km":1., "azimuth_deg":20.}]
        m = folium.Map(location=[50, 14], zoom_start=9)
        env.layer_group(m, items)
        env.add_legend(m, items)
        html = m.get_root().render()
        self.assertIn("Test forest", html)
        self.assertIn("MAP LEGEND", html)
        kml = env.kml_bytes(items)
        self.assertIn("Test forest".encode(), kml)
        ET.fromstring(kml)
        self.assertGreater(len(env.legend_png(items, [("FL100", "#00ff00")])), 100)
        archive = env.export_bundle(items, html.encode())
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertIn("environment/legend.png", z.namelist())
            self.assertIn("map/interactive_map.html", z.namelist())
            self.assertIn("environment/environment.geojson", z.namelist())
            self.assertIn("environment/environment.kml", z.namelist())

    def test_airport_export(self):
        samples = [{"name":"Test Airport","icao":"LKXX","type":"small_airport",
                    "lat":50.0,"lon":14.0,"distance_km":0,
                    "elevation_ft":"1000"}]
        self.assertIn(b"LKXX", aviation.geojson_bytes(samples))
        self.assertIn(b"LKXX", aviation.csv_bytes(samples))
        ET.fromstring(aviation.kml_bytes(samples))

    def test_ray_sector_preselection(self):
        az = np.arange(360, dtype=float)
        polygon = [(100, 100), (101, 100), (101, 101), (100, 101)]
        indices = _polygon_ray_indices(az, Polygon(polygon), polygon)
        self.assertIn(45, list(indices))
        self.assertLess(len(indices), 5)
        across_north = [(1, 100), (-1, 100), (-1, 102), (1, 102)]
        north = _polygon_ray_indices(az, Polygon(across_north), across_north)
        self.assertIn(0, list(north))
        around_radar = [(-1,-1),(-1,1),(1,1),(1,-1)]
        self.assertEqual(len(_polygon_ray_indices(az, Polygon(around_radar),
                                                  around_radar)), 360)

    def test_microsoft_tile_index(self):
        self.assertEqual(len(microsoft.quadkey(50.0, 14.0)), 9)
        self.assertEqual(len(set(microsoft.surrounding_quadkeys(50., 14., .5))), 1)


if __name__ == "__main__":
    unittest.main()
