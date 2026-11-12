"""Fixed 100–9000 ft output-height catalog regression."""
import pathlib
import unittest
import radar_core as core


class StandardAltitudeCatalogTests(unittest.TestCase):
    def test_single_set_for_all_radars(self):
        expected=tuple(range(100,9001,100))
        self.assertEqual(len(expected),90)
        self.assertEqual(core.STANDARD_LEVELS_FT,expected)
        for mode in ("PAR","PAR-NG","RL-2000","SSR"):
            self.assertEqual(core.flight_levels_for(mode),expected)
            for height in expected:
                self.assertTrue(core.valid_flight_level(mode,height))
            for invalid in (0,50,150,950,9001,10000,66000,True,100.5,"100"):
                self.assertFalse(core.valid_flight_level(mode,invalid))

    def test_freeform_parser_does_not_allow_other_altitudes(self):
        self.assertEqual(core.parse_par_flight_levels("100, 200; 9000"),(100,200,9000))
        self.assertEqual(core.parse_par_flight_levels(""),())
        for raw in ("50","150","750","9500","66000","FL100","1.5","-100"):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                core.parse_par_flight_levels(raw)

    def test_editor_has_no_custom_height_inputs(self):
        src=(pathlib.Path(__file__).resolve().parents[1]/
             "map_workspace.py").read_text(encoding="utf-8")
        self.assertIn('def _par_standard_levels_info(',src)
        self.assertNotIn('def _par_free_levels_editor(',src)
        self.assertNotIn('st.form_submit_button("＋ PŘIDAT HLADINY"',src)
        self.assertIn('st.session_state["ws_levels"]=list(core.STANDARD_LEVELS_FT)',src)
        self.assertIn('def _chosen_levels(',src)


if __name__=="__main__":
    unittest.main()
