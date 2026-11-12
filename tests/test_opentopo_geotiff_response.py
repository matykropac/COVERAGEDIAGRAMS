"""OpenTopography GeoTIFF response safety and server-cache regressions."""
import io
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import radar_core as core


class OpenTopoResponseTests(unittest.TestCase):
    def test_raw_tiff_payload_is_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"test.tif"
            header=b"II*\x00"
            path.write_bytes(header+b"binary-data")
            core._normalize_dem_payload(path,path.read_bytes()[:16],
                                        "image/tiff",lambda _:None)
            self.assertEqual(path.read_bytes()[:4],header)

    def test_zip_tiff_is_unpacked(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"test.tif"
            with zipfile.ZipFile(path,"w") as z:
                z.writestr("output/dem.tif",b"II*\x00"+"".encode()+b"tiff-body")
            core._normalize_dem_payload(path,path.read_bytes()[:16],
                                        "application/zip",lambda _:None)
            self.assertTrue(path.read_bytes().startswith(b"II*\x00"))
            self.assertFalse(Path(str(path)+".unpacked").exists())

    def test_gzip_tiff_is_unpacked(self):
        import gzip
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"test.tif"
            path.write_bytes(gzip.compress(b"II*\x00"+b"tiff-body"))
            core._normalize_dem_payload(path,path.read_bytes()[:16],
                                        "application/gzip",lambda _:None)
            self.assertTrue(path.read_bytes().startswith(b"II*\x00"))

    def test_html_api_error_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"test.tif"
            path.write_bytes(b'<html><body>API quota exceeded</body></html>')
            with self.assertRaisesRegex(ValueError,"API quota exceeded"):
                core._normalize_dem_payload(path,path.read_bytes()[:128],
                                            "text/html",lambda _:None)

    def test_other_binary_content_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"test.tif"
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
            with self.assertRaisesRegex(ValueError,"PNG"):
                core._normalize_dem_payload(path,path.read_bytes()[:16],
                                            "image/png",lambda _:None)

    def test_bad_zip_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"test.tif"
            path.write_bytes(b"PK\x03\x04 broken")
            with self.assertRaisesRegex(ValueError,"ZIP"):
                core._normalize_dem_payload(path,path.read_bytes()[:16],
                                            "application/zip",lambda _:None)

    def test_good_geo_tiff_metadata_validation(self):
        try:
            import rasterio
            from rasterio.transform import from_origin
            import numpy as np
        except ImportError:
            self.skipTest("rasterio unavailable")
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"valid.tif"
            with rasterio.open(path,"w",driver="GTiff",height=5,width=5,
                               count=1,dtype="float32",crs="EPSG:4326",
                               transform=from_origin(14,51,.01,.01)) as dst:
                dst.write(np.ones((5,5),dtype="float32"),1)
            self.assertTrue(core._validated_dem(path))


if __name__=="__main__":
    unittest.main()
