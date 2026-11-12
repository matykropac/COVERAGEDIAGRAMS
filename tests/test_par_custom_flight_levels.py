"""PAR-NG custom flight-level acceptance and project persistence."""
import io
import unittest
from zipfile import ZipFile
import json

import radar_core as core


class ParCustomFlightLevelsTests(unittest.TestCase):
    def test_presets_remain_available(self):
        self.assertEqual(core.PAR_LOW_LEVELS_FT, (50,100,150,200,250,300,350,400,450))
        self.assertIn(3000,core.flight_levels_for("PAR-NG"))

    def test_default_par_heights_2000_to_6000(self):
        heights=core.PAR_DEFAULT_LEVELS_FT
        self.assertEqual(len(heights),41)
        self.assertEqual(heights[0],2000)
        self.assertEqual(heights[-1],6000)
        self.assertTrue(all(b-a==100 for a,b in zip(heights,heights[1:])))
        self.assertEqual(len(set(heights)),41)

    def test_parse_custom_integer_heights(self):
        self.assertEqual(core.parse_par_flight_levels("300, 400; 900 1500"),
                         (300,400,900,1500))
        self.assertEqual(core.parse_par_flight_levels("1250,750,1250"),
                         (750,1250))
        self.assertEqual(core.parse_par_flight_levels(""),())

    def test_bad_values_are_rejected(self):
        for raw in ("0","66001","1.5","FL100","50ft","-10",
                    ",".join(["2"]*(core.PAR_CUSTOM_MAX_COUNT+1))):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                core.parse_par_flight_levels(raw)

    def test_modes_are_isolated(self):
        self.assertTrue(core.valid_flight_level("PAR-NG",750))
        self.assertFalse(core.valid_flight_level("SSR",750))
        self.assertFalse(core.valid_flight_level("RL-2000",750))
        self.assertFalse(core.valid_flight_level("PAR-NG",750.5))
        self.assertFalse(core.valid_flight_level("PAR-NG",True))

    def test_project_load_accepts_par_custom(self):
        # Reuse established project test fixture to avoid generating a large
        # radar computation in this test.
        import pathlib
        source=(pathlib.Path(__file__).resolve().parents[1]/
                "project_file.py").read_text(encoding="utf-8")
        self.assertIn("core.valid_flight_level(config.radar_mode,l)",source)
        self.assertIn("core.valid_flight_level(result['config'].radar_mode,ft)",source)

    def test_workspace_uses_custom_in_map_and_export(self):
        import pathlib
        source=(pathlib.Path(__file__).resolve().parents[1]/
                "map_workspace.py").read_text(encoding="utf-8")
        self.assertIn('def _par_free_levels_editor(',source)
        self.assertIn('def _apply_par_free_levels(',source)
        self.assertIn('_par_free_levels_editor("radar")',source)
        self.assertIn('_par_free_levels_editor("map")',source)
        self.assertIn('st.form_submit_button("POUŽÍT CELÝ SEZNAM"',source)
        self.assertIn('st.form_submit_button("＋ PŘIDAT HLADINY"',source)
        self.assertIn('def _on_radar_level_mode_change(',source)
        self.assertIn('def _ensure_par_level_defaults(',source)
        self.assertIn('st.session_state["_par_levels_initialized"]=cfg.radar_mode=="PAR-NG"',source)
        self.assertNotIn('key="ws_par_custom_input"',source)
        self.assertIn("def _chosen_levels(",source)
        self.assertIn("levels=_chosen_levels(c.radar_mode)",source)
        self.assertIn("possible=_available_levels(",source)
        viewer=(pathlib.Path(__file__).resolve().parents[1]/
                "coverage_viewer.py").read_text(encoding="utf-8")
        self.assertIn("core.valid_flight_level(mode,ft)",viewer)


if __name__=="__main__":
    unittest.main()
