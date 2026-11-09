"""Runway geometry unit tests independent of external network."""
import unittest

from airport_geometry import (
    airport_runways, runway_geometry, par_bearing_for_runway,
    validate_icao, validate_saved_geometry,
)


def fixture_rows():
    return [{
        "airport_ident":"TEST","id":"123","closed":"0",
        "le_ident":"18","he_ident":"36",
        "le_latitude_deg":"50.00","le_longitude_deg":"15.00",
        "he_latitude_deg":"49.98","he_longitude_deg":"15.00",
        "le_displaced_threshold_ft":"100",
        "he_displaced_threshold_ft":"0",
        "length_ft":"7300","width_ft":"150",
    }]


class AirportGeometryTests(unittest.TestCase):
    def test_icao_accepts_only_four_letters(self):
        self.assertEqual(validate_icao("lkpd"), "LKPD")
        for code in ("", "LKPD/", "https://example.com", "LKP2"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate_icao(code)

    def test_runway_geometry_uses_displaced_threshold(self):
        runway = airport_runways("TEST", fixture_rows())[0]
        shapes = runway_geometry([runway], extension_nm=10)
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0]["label"], "18 / 36")
        self.assertEqual(len(shapes[0]["extended"]), 4)
        self.assertLess(runway["thresholds"][0][0], runway["ends"][0]["lat"])
        self.assertLess(runway["midpoint"][0], runway["ends"][0]["lat"])
        self.assertGreater(runway["midpoint"][0], runway["ends"][1]["lat"])
        self.assertTrue(178 < runway["heading_deg_true"] < 182)
        self.assertFalse(runway["verified_aip"])

    def test_par_bearing_matches_selected_approach_side(self):
        runway = airport_runways("TEST", fixture_rows())[0]
        north = par_bearing_for_runway(runway, 0, 49.99, 15.0)
        south = par_bearing_for_runway(runway, 1, 49.99, 15.0)
        self.assertLess(min(abs(north), abs(north-360)), 1)
        self.assertLess(abs(south-180), 1)

    def test_missing_endpoint_is_not_guessed(self):
        rows = fixture_rows()
        rows[0]["he_latitude_deg"] = ""
        with self.assertRaisesRegex(ValueError, "souřadnice"):
            airport_runways("TEST", rows)

    def test_saved_geometry_validates_coordinates_and_source(self):
        runway = airport_runways("TEST", fixture_rows())[0]
        code, items = validate_saved_geometry("TEST", [runway])
        self.assertEqual(code, "TEST")
        self.assertEqual(len(items), 1)
        runway["midpoint"] = [900., 15.]
        with self.assertRaises(ValueError):
            validate_saved_geometry("TEST", [runway])


if __name__ == "__main__":
    unittest.main()
