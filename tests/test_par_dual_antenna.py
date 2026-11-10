"""PAR-NG two-channel selection without fabricated RF calibration."""
import dataclasses
import unittest
import numpy as np
import radar_core as core


class DualParCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=core.builtin_par_pattern()

    def test_default_mode_is_both(self):
        self.assertEqual(self.base.channel_mode,"BOTH")
        self.base.validate_model()

    def test_each_channel_is_selectable_and_distinct(self):
        # At the center of the 3D diagram, the AZ supplied pattern is at a
        # different gain from an ideal EL beam, except by coincidence.
        angles=np.deg2rad(np.array([[0.,1.,7.,14.,20.]]))
        az=np.zeros((1,5))
        az_model=dataclasses.replace(self.base,channel_mode="AZ")
        el_model=dataclasses.replace(self.base,channel_mode="EL")
        both=dataclasses.replace(self.base,channel_mode="BOTH")
        az_f=az_model.effective_range_factor(angles,az)
        el_f=el_model.effective_range_factor(angles,az)
        together=both.effective_range_factor(angles,az)
        np.testing.assert_allclose(together,np.minimum(az_f,el_f))
        np.testing.assert_allclose(az_f,az_model.channel_range_factors(angles,az)[0])
        np.testing.assert_allclose(el_f,el_model.channel_range_factors(angles,az)[1])
        self.assertLess(el_f[0,-1],1e-6) # outside Y8600 EL scan
        self.assertEqual(el_f.shape,(1,5))

    def test_no_sum_or_averaging_of_channels(self):
        p=dataclasses.replace(self.base,channel_mode="BOTH")
        theta=np.deg2rad(np.linspace(-1,20,40))
        relative=np.zeros_like(theta)
        a,b=p.channel_range_factors(theta,relative)
        np.testing.assert_allclose(p.effective_range_factor(theta,relative),
                                   np.minimum(a,b))
        self.assertTrue(np.all(p.effective_range_factor(theta,relative)<=a))
        self.assertTrue(np.all(p.effective_range_factor(theta,relative)<=b))

    def test_fixed_3d_requires_independent_el_measurement(self):
        for channel in ("EL","BOTH"):
            with self.subTest(channel=channel),self.assertRaisesRegex(ValueError,"EL"):
                dataclasses.replace(self.base,scan_mode="FIXED_3D",
                                    channel_mode=channel).effective_range_factor(
                                    np.deg2rad(4.),0.)
        dataclasses.replace(self.base,scan_mode="FIXED_3D",
                            channel_mode="AZ").effective_range_factor(
                            np.deg2rad(4.),0.)

    def test_invalid_channels_rejected(self):
        with self.assertRaisesRegex(ValueError,"kanálu"):
            dataclasses.replace(self.base,channel_mode="COMBINED").validate_model()

    def test_workspace_persistence_and_stale_detection(self):
        from pathlib import Path
        src=Path(__file__).resolve().parents[1].joinpath("map_workspace.py").read_text(
            encoding="utf-8")
        self.assertIn('key="ws_par_channels"',src)
        self.assertIn('"channel_mode":"ws_par_channels"',src)
        self.assertIn('"channel_mode":st.session_state.get("ws_par_channels","BOTH")',src)
        self.assertIn('values["channel_mode"]="AZ"',src)
        self.assertIn('_par_model_metadata()!=_par_pattern_metadata(',src)


if __name__=="__main__":
    unittest.main()
