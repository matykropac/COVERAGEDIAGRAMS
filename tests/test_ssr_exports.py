import ast
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from matplotlib.figure import Figure
import radar_core as core
import web_support


class SSRExports(unittest.TestCase):
    def test_shared_physics_and_metadata_are_identical(self):
        root=Path(__file__).parents[1]
        names=('Config','GenericSSRPattern','generic_ssr_pattern','radar_preset','pattern_allows',
               'solve','calculation_metadata','antenna_plot')
        def definitions(path):
            return {n.name:ast.dump(n) for n in ast.parse(path.read_text()).body
                    if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names}
        self.assertEqual(definitions(root/'radar_core.py'),definitions(root/'COVERAGEDIAGRAMS.py'))

    def test_friis_vectorized_matches_scalar_and_broadcasts(self):
        from radar_equations import friis_max_range_m
        gains = np.array([[10., 20., 30.], [15., 25., 35.]])
        losses = np.array([0., 2., 4.])
        result = friis_max_range_m(60., gains, 0., -80., 1030e6, losses)
        expected = np.array([
            [friis_max_range_m(60., float(g), 0., -80., 1030e6, float(l))
             for g, l in zip(row, losses)] for row in gains])
        self.assertEqual(result.shape, gains.shape)
        np.testing.assert_allclose(result, expected, rtol=1e-12)
        self.assertIsInstance(friis_max_range_m(60., 10., 0., -80., 1030e6), float)
        with self.assertRaises(ValueError):
            friis_max_range_m(60., np.array([10., np.nan]), 0., -80., 1030e6)

    def test_exported_assumptions_and_blake_plot(self):
        c=core.Config(radar_mode='SSR',range_km=256*1.852,csc_range_km=256*1.852,
                      step_m=2000,az_step=5,csc_enabled=True,target_m=12000)
        az,d=core.axes(c)
        result=core.solve(c,np.zeros((len(az),len(d))),0,core.generic_ssr_pattern())
        for kind in ('Metadata · JSON','RAW · NPZ','GeoPackage · vektory','GeoTIFF · rastr'):
            blob,name,mime=web_support.export_bytes(kind,result,[10000],0,300,.4,{})
            self.assertGreater(len(blob),100)
            if kind=='Metadata · JSON':
                self.assertEqual(json.loads(blob)['ssr_model']['assumptions']['uplink_mhz'],1030)
            elif kind=='RAW · NPZ':
                import io
                with np.load(io.BytesIO(blob)) as data:
                    self.assertEqual(json.loads(str(data['metadata_json']))['ssr_model']['range_limit_nm'],256)
                    self.assertEqual(data['status'].shape,result['status'].shape)
        fig=Figure(figsize=(8,9))
        core.technical_plot(fig,result=result)
        self.assertIn('Blake',fig.axes[1].get_title())
        fig.savefig('/tmp/ssr_blake_check.png',dpi=100)
        fig.clear()
