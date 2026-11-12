"""Carrier references and physics regression from Y7252A/ZG017A/Y8600."""
import pathlib
import unittest

from radar_frequency_info import (
    RADAR_UI_MODES,frequency_report,wavelength_m,
    radar_echo_power_dbw,PSR_RL2000_CARRIERS_MHZ,
    PSR_RL2000_PEAK_POWER_W,PSR_RL2000_LOW_BEAM_GAIN_DBI,
)
from radar_core import SSR_ASSUMPTIONS
from par_y8600_spec import FREQUENCY_SET_1_MHZ,FREQUENCY_SET_2_MHZ


class RadarFrequencyReportTests(unittest.TestCase):
    def test_four_real_radar_buttons_exist(self):
        self.assertEqual(RADAR_UI_MODES,("PSR","SSR","ASR","PAR"))
        source=(pathlib.Path(__file__).resolve().parents[1]/
                "map_workspace.py").read_text(encoding="utf-8")
        self.assertNotIn('key="ws_radar_selector"',source)
        self.assertNotIn('st.segmented_control(\n                        "RADAROVÝ SYSTÉM"',source)
        self.assertIn('st.button(mode_name,key="ws_radar_button_"+mode_name',source)
        self.assertIn('key="ws_radar_site_from_section"',source)
        self.assertIn('key="ws_save_site_sidebar"',source)
        self.assertIn('def _render_frequency_inventory(',source)

    def test_psr_y7252a_four_frequency_diversity(self):
        self.assertEqual(PSR_RL2000_CARRIERS_MHZ,(2812,2828,2844,2860))
        for mode in ("PSR","ASR"):
            report=frequency_report(mode)
            for f in PSR_RL2000_CARRIERS_MHZ:
                self.assertIn(str(f),report["headline"])
            self.assertIn("RF ROVNICE",report["method"])
        self.assertIn("PSR složku",frequency_report("ASR")["note"])

    def test_y8600_both_operational_sets_and_wavelengths(self):
        self.assertEqual(FREQUENCY_SET_1_MHZ,(9110,9130,9210,9230))
        self.assertEqual(FREQUENCY_SET_2_MHZ,(9150,9180,9250,9280))
        report=frequency_report("PAR")
        for channels,row in zip((FREQUENCY_SET_1_MHZ,FREQUENCY_SET_2_MHZ),
                                report["rows"]):
            self.assertEqual(row[1],", ".join(map(str,channels))+" MHz")
        self.assertIn("kalibrovaný",report["note"])

    def test_mssr_uses_correct_carriers_in_friis(self):
        report=frequency_report("SSR")
        self.assertEqual(float(SSR_ASSUMPTIONS["uplink_mhz"]),1030.)
        self.assertEqual(float(SSR_ASSUMPTIONS["downlink_mhz"]),1090.)
        self.assertIn("1030 MHz",report["rows"][0][1])
        self.assertIn("1090 MHz",report["rows"][1][1])
        self.assertIn("Friis",report["method"])

    def test_physical_wavelength_and_monostatic_frequency_dependency(self):
        self.assertAlmostEqual(wavelength_m(2812),299_792_458/(2812e6))
        a=radar_echo_power_dbw(2812,148.16,
           power_w=PSR_RL2000_PEAK_POWER_W,
           tx_gain_dbi=PSR_RL2000_LOW_BEAM_GAIN_DBI,
           rx_gain_dbi=PSR_RL2000_LOW_BEAM_GAIN_DBI)
        b=radar_echo_power_dbw(2860,148.16,
           power_w=PSR_RL2000_PEAK_POWER_W,
           tx_gain_dbi=PSR_RL2000_LOW_BEAM_GAIN_DBI,
           rx_gain_dbi=PSR_RL2000_LOW_BEAM_GAIN_DBI)
        self.assertGreater(a,b)
        self.assertAlmostEqual(a-b,20*__import__("math").log10(2860/2812),places=8)
        self.assertLess(radar_echo_power_dbw(2812,200,
             power_w=25000,tx_gain_dbi=34.3,rx_gain_dbi=34.3),a)

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            frequency_report("MSSR-UNKNOWN")


if __name__=="__main__":
    unittest.main()
