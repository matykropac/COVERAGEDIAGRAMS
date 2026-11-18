"""Regression tests for PAR scan-beam overlap and raw RF boundaries."""
import dataclasses
import unittest
import numpy as np
import radar_core as core


class OverlappingBeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pattern = core.builtin_par_pattern()

    def test_neighbouring_az_beam_can_win_over_nearest(self):
        # Deliberately offset response: nearest-command-only evaluation
        # incorrectly rejects an echo available from the adjacent command.
        p = dataclasses.replace(self.pattern, az_beam_step_deg=0.3,
                                steering_loss_db_per_deg=0.0)
        p._sample_3d_gain = lambda elevation, offset: np.where(
            np.abs(np.asarray(offset) + 0.16) < 0.025, 0., -80.)
        target = np.array([0.14])
        az_factor, _ = p.channel_range_factors(np.deg2rad(np.array([4.])),
                                                target)
        self.assertGreater(float(az_factor[0]), 0.9)

    def test_az_boundary_has_no_nearest_beam_discontinuity(self):
        p = dataclasses.replace(self.pattern, az_beam_step_deg=0.3,
                                steering_loss_db_per_deg=0.0)
        p._sample_3d_gain = lambda elevation, offset: (
            -12. * (np.asarray(offset) / 0.4) ** 2)
        values, _ = p.channel_range_factors(
            np.deg2rad(np.full(2, 4.)),
            np.array([0.1499, 0.1501]))
        self.assertLess(abs(float(values[0] - values[1])), 0.01)

    def test_no_extension_past_instrumented_sector(self):
        p = dataclasses.replace(self.pattern)
        az, el = p.channel_range_factors(
            np.deg2rad(np.full(4, 4.)),
            np.array([-15.01, -15., 15., 15.01]))
        self.assertLess(az[0], 1e-6)
        self.assertLess(el[0], 1e-6)
        self.assertLess(az[-1], 1e-6)
        self.assertLess(el[-1], 1e-6)


if __name__ == "__main__":
    unittest.main()
