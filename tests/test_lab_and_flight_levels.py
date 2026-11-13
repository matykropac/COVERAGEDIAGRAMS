"""Regression guards for mode-specific flight levels and antenna lab limits."""
import unittest

import radar_core as core
from antenna_lab import MAX_FILE, MAX_POINTS, read_pattern


class FlightLevelCatalogTests(unittest.TestCase):
    def test_psr_ssr_standard_high_altitude_catalog(self):
        expected=(2000,3000,4000,5000,6000,7000,9000,10000,12000,
                  15000,20000,25000,30000,35000,40000,
                  45000,50000,55000,60000,66000)
        for mode in ("RL-2000","SSR"):
            with self.subTest(mode=mode):
                self.assertEqual(core.flight_levels_for(mode),expected)
                self.assertTrue(core.valid_flight_level(mode,66000))
                self.assertFalse(core.valid_flight_level(mode,100))
                self.assertFalse(core.valid_flight_level(mode,42000))

    def test_par_remains_low_altitude(self):
        levels=core.flight_levels_for("PAR-NG")
        self.assertEqual(levels,tuple(range(100,9001,100)))
        self.assertFalse(core.valid_flight_level("PAR-NG",66000))
        self.assertTrue(core.valid_flight_level("PAR-NG",3000))

    def test_lab_import_size_and_1d_validation(self):
        self.assertEqual(MAX_FILE,200*1024*1024)
        self.assertGreaterEqual(MAX_POINTS,20000)
        angle,gain=read_pattern(b"angle,gain\n-2,-25\n0,0\n2,-25\n")
        self.assertEqual(angle.tolist(),[-2.,0.,2.])
        self.assertEqual(gain.tolist(),[-25.,0.,-25.])

    def test_lab_duplicate_angle_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError,"Duplicitn"):
            read_pattern(b"-2,-10\n-2,-20\n0,0\n")


if __name__=="__main__":
    unittest.main()
