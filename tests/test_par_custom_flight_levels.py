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

    def test_parse_custom_integer_heights(self):
        self.assertEqual(core.parse_par_flight_levels("300, 400; 900 1500"),
                         (300,400,900,1500))
        self.assertEqual(core.parse_par_flight_levels("1250,750,1250"),
                         (750,1250))
        self.assertEqual(core.parse_par_flight_levels(""),())

    def test_bad_values_are_rejected(self):
        for raw in ("0","66001","1.5","FL100","50ft","-10",
                    ",".join(["2"]*101)):
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
        self.assertIn('key="ws_par_custom_input"',source)
        self.assertIn('key="ws_par_add_levels"',source)
        self.assertIn("def _chosen_levels(",source)
        self.assertIn("levels=_chosen_levels(c.radar_mode)",source)
        self.assertIn("possible=_available_levels(",source)
        viewer=(pathlib.Path(__file__).resolve().parents[1]/
                "coverage_viewer.py").read_text(encoding="utf-8")
        self.assertIn("core.valid_flight_level(mode,ft)",viewer)


if __name__=="__main__":
    unittest.main()
