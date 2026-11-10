"""AIP connectivity and Y8600 model regression tests."""
import unittest
from unittest.mock import patch
import io
from urllib.error import HTTPError

import aviation_basemap as aip
import par_y8600_spec as y8600


class AipAndY8600Tests(unittest.TestCase):
    def test_aip_without_key(self):
        with patch.object(aip,"configured_key",return_value=None):
            ok,message=aip.test_tiles_connection()
        self.assertFalse(ok)
        self.assertIn("OPENAIP_API_KEY",message)

    def test_aip_http_errors_do_not_leak_url_or_key(self):
        for code in (401,403,429):
            with self.subTest(code=code):
                with patch("urllib.request.urlopen",side_effect=HTTPError(
                        "https://secret.example/?apiKey=SECRET",code,"Error",{},io.BytesIO())):
                    ok,message=aip.test_tiles_connection(key="SECRET")
                self.assertFalse(ok)
                self.assertIn(str(code),message)
                self.assertNotIn("SECRET",message)

    def test_aip_success(self):
        class Response:
            status=200
            headers={"Content-Type":"image/png"}
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,n=-1): return bytes((137,80,78,71,13,10,26,10))
        with patch("urllib.request.urlopen",return_value=Response()):
            ok,message=aip.test_tiles_connection(key="TEST")
        self.assertTrue(ok)

    def test_y8600_two_antennas_are_distinct(self):
        self.assertEqual(y8600.AZIMUTH_ANTENNA.axis,"AZ")
        self.assertEqual(y8600.ELEVATION_ANTENNA.axis,"EL")
        self.assertEqual(y8600.AZIMUTH_ANTENNA.beamwidth_limit_deg,.9)
        self.assertEqual(y8600.ELEVATION_ANTENNA.beamwidth_limit_deg,.65)
        self.assertEqual(y8600.CPI_PULSES,12)
        self.assertEqual(y8600.INSTRUMENTED_RANGE_KM,40.0)


if __name__=="__main__":
    unittest.main()
