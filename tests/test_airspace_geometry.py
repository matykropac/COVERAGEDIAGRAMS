"""CTR/TMA vector layer validation, filtering and API failure recovery."""
import json
import unittest

from airspace_geometry import (
    fetch_airspaces, as_geojson, import_geojson, validate_saved_airspaces,
    visible_airspaces, _geometry_valid,
)


def square(x=15., y=50.):
    return {"type":"Polygon","coordinates":[[
        [x-.04,y-.04],[x+.04,y-.04],[x+.04,y+.04],
        [x-.04,y+.04],[x-.04,y-.04]]]}


def item(kind=4,name="TEST CTR"):
    return {"_id":name,"type":kind,"name":name,"icaoClass":3,
            "lowerLimit":{"value":0,"unit":1,"referenceDatum":0},
            "upperLimit":{"value":4500,"unit":1,"referenceDatum":1},
            "geometry":square()}


class AirspaceVectorTests(unittest.TestCase):
    def test_lookup_filters_types_and_bounds(self):
        def fetch(url):
            self.assertIn("pos=50.000000%2C15.000000",url)
            self.assertIn("dist=80000",url)
            return {"items":[item(),item(7,"TEST TMA"),item(1,"Restricted")],
                    "totalPages":1}
        zones=fetch_airspaces(50,15,80,"secret",fetch=fetch)
        self.assertEqual([z["kind"] for z in zones],["CTR","TMA"])
        self.assertEqual(zones[0]["class"],"D")

    def test_invalid_geojson_is_rejected(self):
        with self.assertRaises(ValueError):
            _geometry_valid({"type":"Polygon","coordinates":[[[900,2],[900,3],
                                                               [901,3],[900,2]]]})

    def test_import_export_keeps_coordinates_and_holes(self):
        geometry={"type":"Polygon","coordinates":[
            [[14.9,49.9],[15.1,49.9],[15.1,50.1],[14.9,50.1],[14.9,49.9]],
            [[14.98,49.98],[14.98,50.02],[15.02,50.02],[15.02,49.98],[14.98,49.98]]]}
        feature={"type":"Feature","geometry":geometry,
                 "properties":{"kind":"CTR","name":"Polygon with hole","class":"D"}}
        raw=json.dumps({"type":"FeatureCollection","features":[feature]}).encode()
        zones=import_geojson(raw)
        self.assertEqual(len(zones),1)
        export=as_geojson(zones)
        self.assertEqual(len(export["features"][0]["geometry"]["coordinates"]),2)

    def test_altitude_filter_keeps_unknown_reference_visible(self):
        zones=fetch_airspaces(50,15,80,"secret",fetch=lambda url:{
            "items":[item()],"totalPages":1})
        self.assertEqual(len(visible_airspaces(zones,altitude_ft=5000)),0)
        self.assertEqual(len(visible_airspaces(zones,altitude_ft=3000)),1)
        zones[0]["upper"]["amsl_ft"]=None
        self.assertEqual(len(visible_airspaces(zones,altitude_ft=5000)),1)

    def test_persistence_rejects_invalid_shapes(self):
        zones=fetch_airspaces(50,15,80,"secret",fetch=lambda url:{
            "items":[item()],"totalPages":1})
        zones[0]["geometry"]["coordinates"][0][0]=[200.,200.]
        with self.assertRaises(ValueError):
            validate_saved_airspaces(zones)

    def test_max_radius_and_key(self):
        with self.assertRaises(ValueError):
            fetch_airspaces(50,15,300,"secret",fetch=lambda url:{})
        with self.assertRaises(ValueError):
            fetch_airspaces(50,15,80,"",fetch=lambda url:{})
