import unittest
from dataclasses import replace
import numpy as np
import radar_core as core


class SSRTests(unittest.TestCase):
    def pattern(self):
        self.assertTrue(hasattr(core, 'generic_ssr_pattern'), 'Generic SSR model is missing')
        return core.generic_ssr_pattern()

    def test_two_independent_one_way_links(self):
        p = self.pattern()
        up, down = p.link_ranges_km(np.deg2rad(8), 0)
        # Friis, each leg has its own transmitter, receiver threshold and wavelength.
        expected_up = 299792458 / (1030e6 * 4*np.pi) * 10**((60+27-3-6+74)/20) / 1000
        expected_down = 299792458 / (1090e6 * 4*np.pi) * 10**((51+27-3-6+82)/20) / 1000
        self.assertAlmostEqual(float(up), expected_up, places=6)
        self.assertAlmostEqual(float(down), expected_down, places=6)
        self.assertEqual(float(p.range_factor(np.deg2rad(8))), 1.)
        # At 40 degrees a -30.72 dB relative gain loss reduces each one-way range.
        up40, down40 = p.link_ranges_km(np.deg2rad(40), 0)
        self.assertAlmostEqual(float(up40/up), 10**(-30.72/20), places=6)
        self.assertLess(float(down40), 256*1.852)

    def test_tilt_and_limit(self):
        p = self.pattern()
        self.assertAlmostEqual(float(p.range_factor(np.deg2rad(35), -1)),
                               float(p.range_factor(np.deg2rad(36), 0)))
        c = core.Config(radar_mode='SSR', range_km=256*1.852, csc_range_km=256*1.852,
                        step_m=1000, az_step=5, csc_enabled=True)
        c.validate()
        for field in ('range_km', 'csc_range_km'):
            with self.assertRaises(ValueError):
                replace(c, **{field: 400.}).validate()
        with self.assertRaises(ValueError):
            core.solve(replace(c, csc_enabled=False), np.zeros((72,475)), 0, p)
        # A high target at the edge of the ground grid exceeds the slant limit.
        self.assertFalse(bool(core.pattern_allows(np.array([c.range_km*1000]),
                                                 30000, 20, c, p)[0]))

    def test_horizon_obstacle_and_unknown_data(self):
        p = self.pattern()
        c = core.Config(radar_mode='SSR', range_km=256*1.852, csc_range_km=256*1.852,
                        step_m=1000, az_step=5, csc_enabled=True, target_m=12000)
        az, d = core.axes(c)
        terrain = np.zeros((len(az),len(d)))
        clear = core.solve(c, terrain, 0, p)
        self.assertEqual(clear['status'][0,100], 1.)
        self.assertEqual(core.status_at_height(clear, 1000)[0,400], 0.)
        terrain[0,10] = 4000
        terrain[1,10] = np.nan
        blocked = core.solve(c, terrain, 0, p)
        self.assertEqual(blocked['status'][0,100], 0.)
        self.assertTrue(np.isnan(blocked['status'][1,100]))
        meta = core.calculation_metadata(blocked)
        self.assertEqual(meta['ssr_model']['range_limit_nm'], 256)
        self.assertIn('assumptions', meta['ssr_model'])


if __name__ == '__main__':
    unittest.main()
