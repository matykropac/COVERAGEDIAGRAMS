"""PAR-NG beam steering, 3D azimuth gain and illustrative detection model."""
import dataclasses
import unittest
import numpy as np
import radar_core as core


class ParThreeDimensionalTests(unittest.TestCase):
    def setUp(self):
        self.pattern=core.builtin_par_pattern()
        self.cfg=core.Config(radar_mode="PAR-NG",range_km=40,
                             csc_range_km=40,step_m=1000,az_step=1,
                             min_elev=-1,max_elev=10,csc_enabled=True)

    def test_static_3d_interpolation_tracks_supplied_grid(self):
        p=dataclasses.replace(self.pattern,scan_mode="FIXED_3D")
        el_i=len(p.angles_deg)//2
        az_i=len(p.azimuths_deg)//2
        e=np.radians(p.angles_deg[el_i])
        az=p.azimuths_deg[az_i]
        g=p.gain_at(e,az,0)
        self.assertAlmostEqual(float(g),float(p.gain_grid_db[el_i,az_i]),places=5)
        outside=p.gain_at(np.radians(100.),0)
        self.assertEqual(float(outside),-200)

    def test_tracking_steering_loss_applies_to_relative_bearing(self):
        p=dataclasses.replace(self.pattern,scan_mode="TRACKING",
                              steering_loss_db_per_deg=0.2)
        e=np.radians(3.)
        self.assertAlmostEqual(float(p.gain_at(e,10)),float(p.gain_at(e,0))-2,places=5)

    def test_detection_albersheim_higher_required_pd_reduces_range(self):
        baseline=dataclasses.replace(self.pattern,detection_model="ALBERSHEIM",pd=.8)
        strict=dataclasses.replace(self.pattern,detection_model="ALBERSHEIM",pd=.95)
        self.assertGreater(strict.required_snr_db(),baseline.required_snr_db())
        self.assertLess(float(strict.effective_range_factor(np.radians(3.),0)),
                        float(baseline.effective_range_factor(np.radians(3.),0)))

    def test_nonzero_scan_loss_changes_edge_not_center(self):
        p=dataclasses.replace(self.pattern,steering_loss_db_per_deg=.5)
        d=np.array([1000.,2000.])
        heights=np.array([[300.,300.],[300.,300.]])
        a=core.pattern_allows(d[None,:],heights,120.,self.cfg,p,azimuths=np.array([[-15.],[0.]]))
        self.assertEqual(a.shape,(2,2))
        self.assertLess(float(p.gain_at(np.radians(3.),15)),float(p.gain_at(np.radians(3.),0)))

    def test_all_par_parameters_validate(self):
        for change in [{"pd":1.0},{"pfa":0.0},{"scan_mode":"UNKNOWN"},
                       {"reference_snr_db":float("nan")},{"pulses":0}]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                dataclasses.replace(self.pattern,**change).validate_model()
