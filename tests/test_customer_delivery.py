"""Light customer export should work without web APIs or Streamlit session."""
import csv
import io
import json
import unittest
from zipfile import ZipFile

import numpy as np
import radar_core as core
from customer_delivery import build_customer_pack, customer_metrics, sector_metrics
from selected_export import build_selected_zip


class CustomerDeliverySmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config=core.Config(lat=50.,lon=15.,range_km=10.,step_m=1000.,
                           az_step=10.,csc_enabled=False)
        terrain,site=core.demo_terrain(config)
        cls.result=core.solve(config,terrain,site)
        cls.result.update(source="TEST synthetic terrain",
                          completed_at="2026-11-05T12:00:00+00:00")

    def test_area_weighted_flight_level_metrics(self):
        rows=customer_metrics(self.result,[5000,10000])
        self.assertEqual(len(rows),2)
        for row in rows:
            value=row["coverage_pct_of_known_area"]
            self.assertGreaterEqual(value,0)
            self.assertLessEqual(value,100)
            self.assertEqual(row["known_terrain_pct"],100)

    def test_customer_pack_pdf_csv_json_and_checksums(self):
        archive=build_customer_pack(self.result,[5000,10000],"Customer Sample")
        with ZipFile(io.BytesIO(archive)) as z:
            paths=z.namelist()
            root="Customer_Pack/"
            self.assertIn(root+"01_Executive_Report.pdf",paths)
            self.assertTrue(z.read(root+"01_Executive_Report.pdf").startswith(b"%PDF-"))
            data=json.loads(z.read(root+"04_Technical_Metadata.json"))
            self.assertEqual(data["title"],"Customer Sample")
            self.assertEqual(len(data["metrics"]),2)
            self.assertIn("05_SHA256SUMS.txt"," ".join(paths))
            csv_data=z.read(root+"02_Coverage_By_Flight_Level.csv").decode("utf-8-sig")
            self.assertEqual(len(list(csv.DictReader(io.StringIO(csv_data)))),2)

    def test_new_customer_pack_does_not_replace_preset(self):
        blob=build_selected_zip(self.result,selected={"customer_pack":True},
                                flight_levels=[5000],index=0,alpha=.5,
                                level_alphas={5000:.5},environment_items=[],
                                customer_name="Client A")
        with ZipFile(io.BytesIO(blob)) as z:
            self.assertIn("07_Customer_Delivery/Customer_Pack/01_Executive_Report.pdf",
                          z.namelist())


if __name__=="__main__":
    unittest.main()
