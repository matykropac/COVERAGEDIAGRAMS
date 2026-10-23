"""Regression tests for engineering diagnostics and angular sampling."""
from dataclasses import replace
import unittest

import numpy as np
from pyproj import Geod

import radar_core as core
from obstacles import apply_obstacles
from coverage_diagnostics import (
    native_azimuth, diagnose, azimuth_coverage_stats, limiting_object
)


def flat_result(terrain=None):
    c = core.Config(
        lat=50., lon=15., antenna_agl=20., range_km=20.,
        step_m=500., az_step=1., min_elev=-1., max_elev=45.,
        target_m=914.4, csc_enabled=False,
    )
    az, distance = core.axes(c)
    if terrain is None:
        terrain = np.full((len(az), len(distance)), 200., dtype=float)
    result = core.solve(c, terrain, 200.)
    result["obstacles"] = []
    return result


class CoverageDiagnosticsTests(unittest.TestCase):
    def test_every_integer_compass_heading_selects_its_native_radial(self):
        result = flat_result()
        headings = []
        for angle in range(360):
            i, native, inside = native_azimuth(result, angle)
            self.assertTrue(inside)
            self.assertEqual(native, float(angle))
            headings.append(i)
        self.assertEqual(len(set(headings)), 360)

    def test_clear_radial_has_no_shadow(self):
        result = flat_result()
        info = diagnose(result, 90, 5.0, 3000)
        self.assertEqual(info["state"], "covered")
        self.assertEqual(info["causes"], [])
        self.assertEqual(info["blocker"]["kind"], "terrain")

    def test_manual_obstacle_is_identified_as_limiting_source(self):
        result = flat_result()
        lon, lat, _ = Geod(ellps="WGS84").fwd(15., 50., 90., 1000.)
        apply_obstacles(result, [dict(kind="point", name="Stožár",
                                      lat=lat, lon=lon, height_m=1000.)])
        info = diagnose(result, 90, 5., 3000)
        self.assertEqual(info["state"], "blocked")
        self.assertEqual(info["blocker"]["name"], "Stožár")
        self.assertIn("Stín zadané překážky", info["causes"])

    def test_terrain_hill_is_identified_as_shadow_source(self):
        result = flat_result()
        raw = result["terrain"].copy()
        raw[90, 1] = 1400.
        result = flat_result(raw)
        info = diagnose(result, 90, 5., 3000)
        self.assertEqual(info["state"], "blocked")
        self.assertEqual(info["blocker"]["kind"], "terrain")
        self.assertIn("Terénní stín (DEM)", info["causes"])

    def test_unknown_dem_remains_unknown(self):
        baseline = flat_result()
        terrain = baseline["terrain"].copy()
        terrain[90, 1] = np.nan
        result = flat_result(terrain)
        info = diagnose(result, 90, 5., 3000)
        self.assertEqual(info["state"], "unknown")
        self.assertIsNone(info["blocker"])
        stats = azimuth_coverage_stats(result, 3000)
        self.assertGreater(stats[90]["unknown_pct"], 0)

    def test_outside_par_sector_not_mapped_to_unrelated_radial(self):
        result = flat_result()
        result["config"] = replace(result["config"], radar_mode="PAR-NG", bearing_deg=0.)
        result["az"] = np.linspace(-15., 15., 31)
        info = diagnose(result, 90, 5., 3000)
        self.assertEqual(info["state"], "outside")

    def test_zero_known_range_uses_none_for_percentage(self):
        result = flat_result()
        result["known"][90, :] = False
        stats = azimuth_coverage_stats(result, 3000)
        self.assertIsNone(stats[90]["covered_pct"])
        self.assertEqual(stats[90]["unknown_pct"], 100.)

    def test_side_view_renders_selected_ray_and_shadow(self):
        from diagnostics_ui import side_view
        result = flat_result()
        info = diagnose(result, 90, 5., 3000)
        fig = side_view(result, info)
        self.assertEqual(len(fig.axes), 1)
        self.assertGreaterEqual(len(fig.axes[0].lines), 2)
        fig.clear()

    def test_restricted_range_stats_are_bounded(self):
        stats = azimuth_coverage_stats(flat_result(), 3000, 0., 10.)
        self.assertEqual(len(stats), 360)
        self.assertTrue(all(0 <= row["covered_pct"] <= 100 for row in stats))


if __name__ == "__main__":
    unittest.main()
