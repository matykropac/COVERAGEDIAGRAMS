"""Regression: RF frequencies shown in UI match exactly what solvers use."""
import pathlib
import unittest

from radar_frequency_info import RADAR_UI_MODES, frequency_report
from radar_core import SSR_ASSUMPTIONS
from par_y8600_spec import FREQUENCY_SET_1_MHZ, FREQUENCY_SET_2_MHZ


class RadarFrequencyReportTests(unittest.TestCase):
    def test_all_four_main_screen_modes_supported(self):
        self.assertEqual(RADAR_UI_MODES,("PSR","SSR","ASR","PAR"))
        for mode in RADAR_UI_MODES:
            info=frequency_report(mode)
            self.assertTrue(info["headline"])
            self.assertTrue(info["method"])
            self.assertTrue(info["rows"])
            self.assertTrue(info["note"])

    def test_ssr_actual_carriers_are_taken_from_friis_model(self):
        info=frequency_report("SSR")
        rows=info["rows"]
        self.assertEqual(rows[0][1],f"{SSR_ASSUMPTIONS['uplink_mhz']:g} MHz")
        self.assertEqual(rows[1][1],f"{SSR_ASSUMPTIONS['downlink_mhz']:g} MHz")
        self.assertIn("Friis",info["method"])

    def test_par_documented_channels_not_claimed_as_active_rf_model(self):
        info=frequency_report("PAR")
        self.assertIn("NEPOUŽITÉ",info["method"])
        for row,source in zip(info["rows"],
                              (FREQUENCY_SET_1_MHZ,FREQUENCY_SET_2_MHZ)):
            self.assertEqual(row[1],", ".join(map(str,source))+" MHz")
        self.assertEqual(tuple(FREQUENCY_SET_1_MHZ),(9110,9130,9210,9230))
        self.assertEqual(tuple(FREQUENCY_SET_2_MHZ),(9150,9180,9250,9280))

    def test_psr_and_asr_do_not_claim_fictitious_carrier(self):
        for mode in ("PSR","ASR"):
            info=frequency_report(mode)
            self.assertIn("není nastavena",info["headline"])
            self.assertIn("bez nosné",info["method"])
        self.assertIn("PSR solveru",frequency_report("ASR")["note"])

    def test_main_screen_uses_a_single_selector_and_opens_chosen_dialog(self):
        source=(pathlib.Path(__file__).resolve().parents[1]/
                "map_workspace.py").read_text(encoding="utf-8")
        self.assertIn('key="ws_radar_selector"',source)
        self.assertIn("on_change=_on_main_radar_selection",source)
        self.assertIn("st.segmented_control(",source)
        self.assertIn("st.session_state[\"ws_open_selected_radar_dialog\"]=True",source)
        self.assertIn("def _render_frequency_inventory(",source)
        self.assertNotIn('key=f"ws_radar_mode_{name}"',source)

    def test_unknown_mode_cannot_be_mislabeled(self):
        with self.assertRaises(ValueError):
            frequency_report("MSSR-UNKNOWN")


if __name__=="__main__":
    unittest.main()
