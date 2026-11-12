"""Low altitude PAR display must keep units explicit and usable."""
import unittest
import numpy as np
import radar_core as core
from web_support import coverage_geojson


class ParAltitudeTests(unittest.TestCase):
    def test_low_levels_exist_and_agl_is_not_amsl(self):
        config=core.Config(radar_mode="PAR-NG",range_km=40,csc_range_km=40,
                           step_m=2000,az_step=5,csc_enabled=True,
                           min_elev=-1,max_elev=10)
        az,dist=core.axes(config)
        terrain=np.full((len(az),len(dist)),650.)
        result=core.solve(config,terrain,650.,core.builtin_par_pattern())
        self.assertTrue(all(ft in core.flight_levels_for("PAR-NG")
                        for ft in (100,200,300,400,500,600,700,800,900)))
        below=core.status_at_height(result,50*core.FT_TO_M,"AMSL")
        above=core.status_at_height(result,50*core.FT_TO_M,"AGL")
        self.assertEqual(np.count_nonzero(below==1),0)
        self.assertGreater(np.count_nonzero(above==1),0)

    def test_geojson_reference_validation(self):
        config=core.Config(radar_mode="PAR-NG",range_km=40,csc_range_km=40,
                           step_m=2000,az_step=5,csc_enabled=True)
        az,dist=core.axes(config)
        result=core.solve(config,np.zeros((len(az),len(dist))),0.,
                          core.builtin_par_pattern())
        with self.assertRaises(ValueError):
            coverage_geojson(result,100,"FL")
