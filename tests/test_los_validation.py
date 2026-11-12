"""LOS validation against analytic flat-earth and spherical-chord cases."""
import unittest
import numpy as np
from los_validation import spherical_chord_clearance, verify_radial_point
import radar_core as core


class IndependentLOSValidationTests(unittest.TestCase):
    def test_equal_height_flat_ground_has_curvature_bulge(self):
        d=np.linspace(1000.,40000.,40)
        ray,clearance=spherical_chord_clearance(
            d,np.zeros_like(d),100.,100.,4/3)
        self.assertAlmostEqual(clearance[-1],100.,places=4)
        self.assertLess(np.min(clearance[:-1]),100.)
        self.assertTrue(np.isfinite(ray).all())

    def test_terrain_ridge_blocks_and_high_target_clears(self):
        distances=np.arange(1000.,21000.,1000.)
        terrain=np.zeros(len(distances))
        terrain[9]=300.
        _,low=spherical_chord_clearance(
            distances,terrain,50.,70.,4/3)
        _,high=spherical_chord_clearance(
            distances,terrain,50.,700.,4/3)
        self.assertLess(low.min(),0.)
        self.assertGreater(high.min(),0.)

    def test_analytical_chord_endpoints(self):
        distance=np.linspace(1000.,40000.,40)
        terrain=np.zeros_like(distance)
        for k in (0.5,4/3,3.):
            ray,_=spherical_chord_clearance(
                distance,terrain,110.,180.,k)
            self.assertAlmostEqual(ray[-1],180.,places=3)

    def test_known_flat_model_agrees_with_solver(self):
        c=core.Config(radar_mode="RL-2000",range_km=20.,
                      step_m=1000.,az_step=5.,min_elev=-1.,
                      max_elev=45.,csc_enabled=False)
        az,d=core.axes(c)
        terrain=np.zeros((len(az),len(d)))
        result=core.solve(c,terrain,0.)
        check=verify_radial_point(result,0,10,600.,reference="AMSL")
        self.assertEqual(check["status"],"MATCH")
        self.assertTrue(check["independent_los"])
        self.assertTrue(check["main_geometry"])

    def test_ridge_and_unknown_dem_do_not_false_pass(self):
        c=core.Config(radar_mode="RL-2000",range_km=20.,
                      step_m=1000.,az_step=5.,min_elev=-1.,
                      max_elev=45.,csc_enabled=False)
        az,d=core.axes(c)
        terrain=np.zeros((len(az),len(d)))
        terrain[:,5]=600.
        result=core.solve(c,terrain,0.)
        check=verify_radial_point(result,0,15,120.,reference="AMSL")
        self.assertFalse(check["independent_los"])
        self.assertEqual(check["status"],"MATCH")
        self.assertFalse(check["main_geometry"])
        terrain[:,4]=np.nan
        result=core.solve(c,terrain,0.)
        unknown=verify_radial_point(result,0,15,120.)
        self.assertEqual(unknown["status"],"UNKNOWN")

    def test_ui_integration_and_independent_algorithm(self):
        from pathlib import Path
        source=(Path(__file__).resolve().parents[1]/
                "map_workspace.py").read_text(encoding="utf-8")
        javascript=(Path(__file__).resolve().parents[1]/
                    "assets/persistent_leaflet.js").read_text(encoding="utf-8")
        validation=(Path(__file__).resolve().parents[1]/
                    "los_validation.py").read_text(encoding="utf-8")
        self.assertIn('("VALIDACE","✓","TEST"',source)
        self.assertIn('def _render_los_validation(',source)
        self.assertIn('type:"validate_los"',javascript)
        self.assertIn('def spherical_chord_clearance(',validation)
        self.assertNotIn("height_at_angle(",validation)
        self.assertNotIn("np.maximum.accumulate(",validation)


if __name__=="__main__":
    unittest.main()
