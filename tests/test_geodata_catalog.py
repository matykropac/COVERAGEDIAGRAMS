"""Regression checks for auto-imported editable geodata obstacles."""
import unittest
from geodata_obstacle_catalog import catalog_from_data, synchronize


class ImportedObstaclesTest(unittest.TestCase):
    def setUp(self):
        self.lat=50.0
        self.lon=15.0
        self.polygons=[
            {"name":"Known building","kind":"Building","source":"OpenStreetMap",
             "source_id":"10","height_m":22.0,
             "coordinates":[[50.01,15.01],[50.01,15.0102],[50.0102,15.0102],[50.0102,15.01]]},
            {"name":"Unknown tower","kind":"Tower","source":"OpenStreetMap",
             "source_id":"11","height_m":None,
             "coordinates":[[50.02,15.02],[50.02,15.0202],[50.0202,15.0202],[50.0202,15.02]]},
        ]
        self.wind=[{"name":"Wind farm 1","osm_id":"W1","lat":50.03,"lon":15.03,
                    "height":"160 m"}]

    def test_catalog_preserves_unknown_height(self):
        data=catalog_from_data(self.polygons,self.wind)
        self.assertEqual(len(data),3)
        self.assertIsNone(data[1]["height_m"])
        self.assertAlmostEqual(data[2]["height_m"],160.0)

    def test_auto_enable_known_and_keep_unknown_unselected(self):
        cat=catalog_from_data(self.polygons,self.wind)
        for item in cat:
            item["enabled"]=item["height_m"] is not None
        active,errors=synchronize([],cat,self.lat,self.lon)
        self.assertEqual(errors,0)
        self.assertEqual(len(active),2)
        self.assertTrue(all(item["catalog_id"] for item in active))
        self.assertFalse(cat[1]["enabled"])

    def test_user_deleted_items_do_not_get_reenabled(self):
        cat=catalog_from_data(self.polygons,self.wind)
        cat[0]["enabled"]=False
        cat[2]["enabled"]=True
        active,errors=synchronize([],cat,self.lat,self.lon,auto_enable=False)
        self.assertEqual(errors,0)
        self.assertEqual(len(active),1)
        self.assertEqual(active[0]["name"],"Wind farm 1")


if __name__=="__main__":
    unittest.main()
