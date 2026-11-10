"""Numerical and interface regression checks for AESA scan acceleration."""
import dataclasses
from io import BytesIO
import json
import unittest
from zipfile import ZipFile

import numpy as np
import radar_core as core
import par_scan_engine as scan
from par_diagnostics_export import make_diagnostics_zip


class AesaScanEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = core.builtin_par_pattern()

    def test_fast_matches_direct_scan_at_command_grid(self):
        base=dataclasses.replace(self.source,scan_mode="TRACKING",
                                 channel_mode="BOTH",gas_loss_db_per_km=0,
                                 rain_loss_db_per_km=0,additional_loss_db=0)
        angles=np.deg2rad(np.array([[-.5,0.,1.,3.,7.,12.,14.]]))
        az=np.array([[-14.,-8.,-2.,0.,5.,10.,15.]])
        fast=scan.channel_factors(dataclasses.replace(base,coverage_mode="FAST"),
                                  angles,az)
        direct=scan.channel_factors(
            dataclasses.replace(base,coverage_mode="ENGINEERING"),angles,az)
        for f,d in zip(fast,direct):
            np.testing.assert_allclose(f,d,rtol=.08,atol=.035)

    def test_two_way_attenuation_reduces_margins(self):
        base=dataclasses.replace(self.source,coverage_mode="ENGINEERING",
                                 scan_mode="TRACKING",channel_mode="BOTH")
        angles=np.deg2rad(np.array([3.,5.]))
        az=np.array([0.,2.])
        distances=np.array([10000.,20000.])
        clear=scan.evaluate(base,angles,az,distances)
        wet=scan.evaluate(dataclasses.replace(base,
                          rain_loss_db_per_km=.08,
                          gas_loss_db_per_km=.02),
                          angles,az,distances)
        np.testing.assert_allclose(
            clear["az_margin_db"]-wet["az_margin_db"],
            2*(.08+.02)*distances/1000.,atol=1e-6)
        np.testing.assert_allclose(
            clear["el_margin_db"]-wet["el_margin_db"],
            2*(.08+.02)*distances/1000.,atol=1e-6)

    def test_both_is_intersection_not_snr_sum(self):
        p=dataclasses.replace(self.source,coverage_mode="FAST",
                              channel_mode="BOTH")
        values=scan.evaluate(p,np.deg2rad(np.array([1.,8.,14.])),
                             np.array([0.,5.,15.]),
                             np.array([4000.,15000.,35000.]))
        np.testing.assert_array_equal(values["both"],
                                       values["az"] & values["el"])
        np.testing.assert_array_equal(values["selected"],values["both"])
        np.testing.assert_allclose(
            values["limiting_margin_db"],
            np.minimum(values["az_margin_db"],values["el_margin_db"]))

    def test_cache_reuses_angular_grid_without_recomputing_terrain(self):
        scan.clear_cache()
        p=dataclasses.replace(self.source,coverage_mode="FAST")
        angles=np.deg2rad(np.array([2.,8.]))
        scan.channel_factors(p,angles,np.array([-1.,1.]))
        self.assertEqual(len(scan._CACHE),1)
        cached=next(iter(scan._CACHE.values()))
        scan.channel_factors(p,angles,np.array([5.,12.]))
        self.assertIs(next(iter(scan._CACHE.values())),cached)

    def test_unknown_quality_and_invalid_losses_rejected(self):
        with self.assertRaises(ValueError):
            dataclasses.replace(self.source,coverage_mode="INVALID").validate_model()
        with self.assertRaises(ValueError):
            dataclasses.replace(self.source,rain_loss_db_per_km=-.1).validate_model()

    def test_solver_channel_diagnostics_share_geometry(self):
        c=core.Config(radar_mode="PAR-NG",range_km=40.,csc_range_km=40.,
                      step_m=2000.,az_step=5.,min_elev=-1.,max_elev=14.,
                      csc_enabled=True)
        terrain=np.full((7,20),200.)
        p=dataclasses.replace(self.source,coverage_mode="FAST",channel_mode="BOTH")
        result=core.solve(c,terrain,200.,p)
        channels=core.par_channel_status_at_height(result,250.,reference="AMSL")
        self.assertEqual(channels["az"].shape,terrain.shape)
        self.assertEqual(channels["el"].shape,terrain.shape)
        self.assertEqual(channels["both"].shape,terrain.shape)
        self.assertTrue(np.all(channels["both"]<=channels["az"]))
        self.assertTrue(np.all(channels["both"]<=channels["el"]))

    def test_leaflet_layer_switch_changes_signature(self):
        from pathlib import Path
        src=Path(__file__).resolve().parents[1].joinpath(
            "map_workspace.py").read_text(encoding="utf-8")
        self.assertIn('signature([active,reference,channel_view,alpha,',src)
        self.assertIn('"LIMIT":"LIMITING · omezující kanál"',src)
        self.assertIn('par_limiting_geojson(',src)
        self.assertIn('par_diagnostic_geojson(',src)
        self.assertIn('key="ws_par_quality"',src)
        self.assertIn('"coverage_mode":"ws_par_quality"',src)

    def test_export_contains_independent_masks_and_margins(self):
        c=core.Config(radar_mode="PAR-NG",range_km=40.,csc_range_km=40.,
                      step_m=2000.,az_step=5.,min_elev=-1.,max_elev=14.,
                      csc_enabled=True)
        p=dataclasses.replace(self.source,coverage_mode="FAST",channel_mode="BOTH")
        result=core.solve(c,np.full((7,20),200.),200.,p)
        payload=make_diagnostics_zip(result,1000,reference="AMSL")
        with ZipFile(BytesIO(payload)) as z:
            names=set(z.namelist())
            for n in ("layers/01_AZ_coverage.geojson",
                      "layers/02_EL_coverage.geojson",
                      "layers/03_JOINT_coverage.geojson",
                      "layers/04_limit_AZ.geojson",
                      "layers/05_limit_EL.geojson",
                      "data/par_channel_margins.npz"):
                self.assertIn(n,names)
            meta=json.loads(z.read("README_parameters.json"))
            self.assertEqual(meta["mode"],"FAST")


if __name__=="__main__":
    unittest.main()
