import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest
import radar_core as core


class RadarUITests(unittest.TestCase):
    def test_web_radar_presets_and_ssr_calculation(self):
        app = AppTest.from_file(str(Path(__file__).parents[1]/'streamlit_app.py'), default_timeout=40).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key='radar').options, ['PSR', 'PAR', 'SSR'])
        self.assertEqual(app.number_input(key='min_elev').value, -1.)
        for nm in (60, 80, 100):
            app.selectbox(key='psr_range_nm').set_value(nm).run()
            self.assertEqual(app.selectbox(key='psr_range_nm').value, nm)
        app.selectbox(key='radar').set_value('SSR').run()
        self.assertFalse(app.exception)
        app.selectbox(key='source').set_value('OpenTopography').run()
        self.assertEqual(app.selectbox(key='dataset_SSR').options, ['COP90', 'SRTMGL3'])
        self.assertEqual(app.selectbox(key='dataset_SSR').value, 'COP90')
        app.selectbox(key='source').set_value('Syntetické demo').run()
        app.button(key='calculate').click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        result = app.session_state['result']
        self.assertEqual(result['config'].range_km, 256*1.852)
        self.assertEqual(result['config'].antenna_tilt_deg, -1.)
        self.assertLessEqual(result['terrain'].size,250000)
        self.assertIsInstance(result['antenna_pattern'],core.GenericSSRPattern)
        app.selectbox(key='radar').set_value('PAR').run()
        app.button(key='calculate').click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.session_state['result']['config'].range_km, 40.)
        app.selectbox(key='radar').set_value('PSR').run()
        app.button(key='calculate').click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertAlmostEqual(app.session_state['result']['config'].range_km, 185.2)
