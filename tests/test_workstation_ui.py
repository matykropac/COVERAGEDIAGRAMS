"""Regression guard for the integrated workstation redesign."""
import unittest

from workspace_theme import header, COMMON_CSS
from viewer_export import render_print
from viewer_workspace_file import make_workspace, load_workspace


class WorkstationTests(unittest.TestCase):
    def test_escaped_project_title(self):
        markup=header("EDITOR",'<script>alert(1)</script>',"READY")
        self.assertIn("COVERAGEDIAGRAMS",markup)
        self.assertNotIn("<script>",markup)
        self.assertIn("&lt;script&gt;",markup)
        self.assertIn("cd-app-header",markup)
        self.assertIn("cd-navy",COMMON_CSS)

    def test_print_requires_visible_data(self):
        with self.assertRaisesRegex(ValueError,"viditelnou vrstvu"):
            render_print({},{},"Empty",fmt="png",dpi=300)

    def test_print_rejects_bad_format(self):
        with self.assertRaises(ValueError):
            render_print({},{},"Empty",fmt="svg",dpi=300)

    def test_editor_workstation_navigation_and_radar_fields(self):
        from pathlib import Path
        text=Path(__file__).resolve().parents[1].joinpath("map_workspace.py").read_text(
            encoding="utf-8")
        for key in ("ws_radar","ws_lat","ws_lon","ws_agl","ws_psr_nm",
                    "ws_bearing","ws_ssr_diagram","ws_source","ws_dem",
                    "ws_dataset","ws_step","ws_azstep","ws_k","ws_min",
                    "ws_max","ws_tilt","ws_par_scan_mode","ws_par_scan_loss",
                    "ws_par_detection","ws_par_snr","ws_par_pd","ws_par_pfa",
                    "ws_par_pulses","ws_beam","ws_target","ws_reference","ws_levels"):
            self.assertIn('key="'+key+'"',text,key)
        self.assertIn("cd-viewer-rail-link",text)
        self.assertIn('st.container(key="cd_nav_rail")',text)
        self.assertIn('f"{symbol}  {label}"',text)
        self.assertNotIn('cd-rail-label',text)
        self.assertIn("ws_export_project_load",text)
        self.assertNotIn('st.segmented_control("Režim",["DAY","NIGHT"]',text)

    def test_viewer_layout_roundtrip(self):
        layers={"FL 030":[{"type":"Feature","properties":{"name":"FL"},
                "geometry":{"type":"Point","coordinates":[15.0,50.0]}}]}
        styles={"FL 030":{"show":True,"color":"#63c9ef","opacity":.5,"width":2.}}
        settings={"viewer_mode":"3D TERÉN / HYPSOMETRIE",
                  "viewer_map_title":"RADAR TEST"}
        blob=make_workspace(layers,styles,settings)
        actual_layers,actual_styles,actual_settings=load_workspace(blob)
        self.assertEqual(layers,actual_layers)
        self.assertEqual(styles,actual_styles)
        self.assertEqual(settings,actual_settings)

    def test_render_vector_pdf(self):
        features={"Test / RWY":[{"type":"Feature",
            "properties":{"name":"Test runway"},
            "geometry":{"type":"LineString","coordinates":[[15.,50.],[15.02,50.01]]}}]}
        style={"Test / RWY":{"show":True,"color":"#63c9ef","opacity":.8,"width":2.}}
        blob=render_print(features,style,"Airport test",fmt="pdf",dpi=300,night=True)
        self.assertTrue(blob.startswith(b"%PDF"))
        self.assertGreater(len(blob),4000)


if __name__=="__main__":
    unittest.main()
