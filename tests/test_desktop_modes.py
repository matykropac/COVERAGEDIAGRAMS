import unittest
from types import SimpleNamespace
import COVERAGEDIAGRAMS as desktop

class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value

class Control:
    def configure(self, **kwargs): pass

class DesktopModes(unittest.TestCase):
    def test_psr_ssr_par_roundtrip_and_terrain_default(self):
        pattern = desktop.rl2000_dual_beam_pattern()
        original = dict(range_km='148.16', csc_range_km='148.16', az_step='1',step_m='500')
        app = SimpleNamespace(busy=False, radar_mode=Value('SSR'), _active_radar_mode='RL-2000',
            vars={key:Value(value) for key,value in original.items()},
            param_entries={key:Control() for key in ('range_km','csc_range_km')},
            antenna_pattern=pattern, par_pattern=desktop.builtin_par_pattern(),
            csc_enabled=Value(True), antenna_name=Value('PSR'), status=Value(''),
            dataset=Value('COP30'), dataset_selector=Control(), schedule_draw=lambda: None)
        desktop.App.radar_mode_changed(app)
        self.assertEqual(app.dataset.get(), 'COP90')
        self.assertEqual(float(app.vars['range_km'].get()), 256*1.852)
        self.assertIsInstance(app.antenna_pattern, desktop.GenericSSRPattern)
        app.radar_mode.set('PAR-NG')
        desktop.App.radar_mode_changed(app)
        self.assertEqual(float(app.vars['range_km'].get()), 40.)
        app.radar_mode.set('RL-2000')
        desktop.App.radar_mode_changed(app)
        self.assertEqual({key:value.get() for key,value in app.vars.items()},original)
        self.assertIs(app.antenna_pattern,pattern)
