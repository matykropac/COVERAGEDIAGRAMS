"""Regression tests for PAR projects recomputed from persisted DEM."""
import unittest
import numpy as np

import radar_core as core
from obstacles import apply_obstacles
from project_file import load_project, save_project


class CachedParRecomputeTests(unittest.TestCase):
    def test_par_project_can_recompute_without_downloading_dem(self):
        config = core.Config(
            radar_mode="PAR-NG", range_km=40, csc_range_km=40,
            step_m=1000, az_step=2, csc_enabled=True,
            min_elev=-1, max_elev=10, antenna_tilt_deg=0)
        az, distance = core.axes(config)
        terrain = np.full((len(az), len(distance)), 100.0)
        original = core.solve(config, terrain, 100.0, core.builtin_par_pattern())
        original["source"] = "TEST DEM"
        project = save_project(original, levels=[3000], obstacles=[])
        loaded, metadata = load_project(project)
        np.testing.assert_array_equal(loaded["terrain"], terrain)
        self.assertIsNone(loaded["antenna_pattern"])
        rebuilt = core.solve(loaded["config"], loaded["terrain"],
                             loaded["site_height"], core.builtin_par_pattern())
        apply_obstacles(rebuilt, metadata["obstacles"])
        np.testing.assert_array_equal(rebuilt["status"], original["status"])
        for level in (300, 3000, 10000):
            np.testing.assert_array_equal(
                core.status_at_height(rebuilt, level * core.FT_TO_M),
                core.status_at_height(original, level * core.FT_TO_M))

    def test_recompute_does_not_inherit_old_obstacle_shadow(self):
        config = core.Config(
            radar_mode="PAR-NG", range_km=40, csc_range_km=40,
            step_m=1000, az_step=2, csc_enabled=True)
        az, distance = core.axes(config)
        terrain = np.full((len(az), len(distance)), 100.0)
        prior = core.solve(config, terrain, 100.0, core.builtin_par_pattern())
        prior["lower"][:] = np.nan
        prior["status"][:] = 0
        restored = core.solve(config, prior["terrain"], prior["site_height"],
                              core.builtin_par_pattern())
        pristine = core.solve(config, terrain, 100.0, core.builtin_par_pattern())
        np.testing.assert_array_equal(restored["status"], pristine["status"])


if __name__ == "__main__":
    unittest.main()
