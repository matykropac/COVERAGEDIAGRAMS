import unittest
from dataclasses import replace
import numpy as np
import radar_core as core
from ssr_custom import load_measured_ssr, MeasuredSSRPattern


class MeasuredSSRTests(unittest.TestCase):
    def test_data_and_gain(self):
        p = load_measured_ssr()
        self.assertIsInstance(p, core.GenericSSRPattern)
        self.assertIsInstance(p, MeasuredSSRPattern)
        self.assertEqual(len(p.angles_deg), 901)
        self.assertAlmostEqual(p.angles_deg[0], -30)
        self.assertAlmostEqual(p.angles_deg[-1], 60)
        self.assertAlmostEqual(float(p.gain_db(np.deg2rad(6.9))), 0)
        self.assertAlmostEqual(float(p.gain_db(np.deg2rad(0))), -5.024)
        self.assertAlmostEqual(float(p.gain_db(np.deg2rad(7.9), 1.0)), 0)
        self.assertLess(float(p.gain_db(np.deg2rad(-6))), -30)

    def test_technical_preview(self):
        from matplotlib.figure import Figure
        c = core.Config(radar_mode='SSR', range_km=core.SSR_RANGE_KM,
                        csc_range_km=core.SSR_RANGE_KM, csc_enabled=True,
                        antenna_tilt_deg=-1)
        fig = Figure()
        core.technical_plot(fig, config=c, pattern=load_measured_ssr())
        self.assertEqual(len(fig.axes), 2)

    def test_ssr_links_and_terrain(self):
        p = load_measured_ssr()
        c = core.Config(radar_mode='SSR', range_km=core.SSR_RANGE_KM,
                        csc_range_km=core.SSR_RANGE_KM, step_m=2000,
                        az_step=5, target_m=9000, csc_enabled=True)
        az, d = core.axes(c)
        terrain = np.zeros((len(az), len(d)))
        result = core.solve(c, terrain, 0, p)
        self.assertEqual(result['terrain'].shape, terrain.shape)
        self.assertIsInstance(result['antenna_pattern'], MeasuredSSRPattern)
        self.assertTrue(np.isfinite(p.link_ranges_km(np.deg2rad(10))[0]))
        self.assertTrue(np.isfinite(p.link_ranges_km(np.deg2rad(10))[1]))
        self.assertEqual(core.calculation_metadata(result)['ssr_model']['range_limit_nm'], 256)


if __name__ == '__main__':
    unittest.main()
