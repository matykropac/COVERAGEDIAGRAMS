"""Map-layer-only exports must work without a radar computation."""
import json
import unittest
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from position_export import (
    make_layer_features, par_helper_features, kml_bytes, kmz_bytes, geojson_bytes,
)


RUNWAY={
    "label":"08 / 26",
    "ends":[{"lat":-22.479,"lon":17.47,"ident":"08"},
            {"lat":-22.482,"lon":17.50,"ident":"26"}],
    "thresholds":[[-22.479,17.47],[-22.482,17.50]],
    "midpoint":[-22.4805,17.485],
    "heading_deg_true":96.4,
    "length_m":3000,"width_m":45,
    "source":"OurAirports public-domain runways.csv",
}
CTR={
    "name":"FYWH CTR","kind":"CTR","class":"D",
    "geometry":{"type":"Polygon","coordinates":[
        [[17.45,-22.50],[17.52,-22.50],[17.52,-22.45],
         [17.45,-22.45],[17.45,-22.50]]]},
    "lower":{"text":"GND","amsl_ft":None},
    "upper":{"text":"7500 ft MSL","amsl_ft":7500},
    "source":"OpenAIP","verified_aip":False,
}
OBSTACLE={
    "kind":"polygon","name":"Known tower",
    "coordinates":[[-22.47,17.48],[-22.47,17.4802],[-22.4702,17.4802]],
    "height_m":60,"source":"manual",
}
FOREST={
    "kind":"Forest","name":"Forest shape",
    "coordinates":[[-22.46,17.48],[-22.46,17.49],[-22.47,17.49]],
    "height_m":None,"height_quality":"unknown",
    "source":"OpenStreetMap",
}


class PositionExportTests(unittest.TestCase):
    def _build(self):
        return make_layer_features(
            runways=[RUNWAY],airspaces=[CTR],obstacles=[OBSTACLE],
            environment=[FOREST],site_lat=-22.48,site_lon=17.48)

    def test_export_without_calculated_radar_result(self):
        features=self._build()
        self.assertEqual(len(features),8)
        by_layer={f["properties"]["layer"] for f in features}
        self.assertEqual(by_layer,{
            "RUNWAY_CENTERLINE","RUNWAY_EXTENDED_AXIS","RUNWAY_THRESHOLDS","RUNWAY_MIDPOINT",
            "CTR","OBSTACLES","GEODATA_FOREST"})

    def test_par_axis_sector_and_runway_parallel_export_to_kml(self):
        helpers=par_helper_features(
            site_lat=-22.48,site_lon=17.48,bearing_deg=96.4,
            range_km=40,runway=RUNWAY,runway_end=0)
        labels={f["properties"]["name"] for f in helpers}
        for sector in ("PŘEDNÍ","ZADNÍ"):
            self.assertIn(f"PAR · osa {sector}",labels)
            self.assertIn(f"PAR · hranice −15° {sector}",labels)
            self.assertIn(f"PAR · hranice +15° {sector}",labels)
            self.assertIn(f"PAR · vnější oblouk ±15° {sector}",labels)
        self.assertIn("PAR · rovnoběžka RWY 08 / 26",labels)
        self.assertIn("PAR · kolmice RWY 08 / 26",labels)
        self.assertIn("RANGE · 260 NM",labels)
        parallel=[f for f in helpers if f["properties"]["layer"]=="PAR_RUNWAY_REFERENCE"][0]
        self.assertEqual(parallel["geometry"]["coordinates"][1],[17.48,-22.48])
        xml=ET.fromstring(kml_bytes(helpers))
        ns={"k":"http://www.opengis.net/kml/2.2"}
        self.assertEqual(len(xml.findall(".//k:Placemark",ns)),len(helpers))
        self.assertEqual(len(xml.findall(".//k:LineString",ns)),len(helpers)-1)

    def test_two_runways_export_all_parallel_and_perpendicular_guides(self):
        second=dict(RUNWAY,key="second",label="17 / 35",
                    heading_deg_true=175.0)
        guides=par_helper_features(
            site_lat=-22.48,site_lon=17.48,bearing_deg=96.4,
            range_km=40,runways=[RUNWAY,second],include_range=False)
        refs=[f for f in guides if f["properties"]["layer"]=="PAR_RUNWAY_REFERENCE"]
        self.assertEqual(len(refs),4)
        names={f["properties"]["name"] for f in refs}
        for label in ("08 / 26","17 / 35"):
            self.assertIn("PAR · rovnoběžka RWY "+label,names)
            self.assertIn("PAR · kolmice RWY "+label,names)
        for item in refs:
            self.assertEqual(item["geometry"]["coordinates"][1],[17.48,-22.48])

    def test_kml_kmz_and_geojson_preserve_geometry_and_attributes(self):
        features=self._build()
        kml=kml_bytes(features)
        root=ET.fromstring(kml)
        ns={"k":"http://www.opengis.net/kml/2.2"}
        names=[x.text for x in root.findall(".//k:Folder/k:name",ns)]
        self.assertIn("CTR",names)
        self.assertIn("OBSTACLES",names)
        self.assertIn("RUNWAY_THRESHOLDS",names)
        self.assertEqual(len(root.findall(".//k:Placemark",ns)),len(features))
        with ZipFile(BytesIO(kmz_bytes(features))) as archive:
            self.assertEqual(archive.namelist(),["doc.kml"])
            self.assertEqual(archive.read("doc.kml"),kml)
        geo=json.loads(geojson_bytes(features))
        self.assertEqual(len(geo["features"]),len(features))
        obstacle=[x for x in geo["features"] if x["properties"]["layer"]=="OBSTACLES"][0]
        self.assertEqual(obstacle["properties"]["height_agl_m"],60)
        forest=[x for x in geo["features"] if x["properties"]["layer"]=="GEODATA_FOREST"][0]
        self.assertIsNone(forest["properties"]["height_agl_m"])

    def test_select_independent_layers(self):
        features=make_layer_features(
            runways=[RUNWAY],airspaces=[CTR],obstacles=[OBSTACLE],
            environment=[FOREST],site_lat=-22.48,site_lon=17.48,
            include_runways=False,include_environment=False)
        self.assertEqual({x["properties"]["layer"] for x in features},
                         {"CTR","OBSTACLES"})

    def test_unknown_coordinate_rejected_not_silently_fixed(self):
        bad=dict(OBSTACLE,coordinates=[[100,17.48],[99,17.48],[99,17.49]])
        with self.assertRaises(ValueError):
            make_layer_features(obstacles=[bad],site_lat=-22.48,site_lon=17.48)
        with self.assertRaises(ValueError):
            make_layer_features(obstacles=[OBSTACLE])

    def test_multiring_ctr_exports_inner_hole(self):
        ctr=dict(CTR,geometry={
            "type":"Polygon","coordinates":[
                [[17.45,-22.5],[17.55,-22.5],[17.55,-22.4],
                 [17.45,-22.4],[17.45,-22.5]],
                [[17.47,-22.48],[17.48,-22.48],[17.48,-22.47],
                 [17.47,-22.47],[17.47,-22.48]]]})
        xml=ET.fromstring(kml_bytes(make_layer_features(
            airspaces=[ctr],include_runways=False,include_obstacles=False,
            include_environment=False)))
        self.assertEqual(len(xml.findall(".//{http://www.opengis.net/kml/2.2}innerBoundaryIs")),1)


if __name__=="__main__":
    unittest.main()
