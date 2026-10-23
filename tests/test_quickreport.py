"""QuickReport regression tests: ZIP layout, every flight level, and print resolution."""
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile
import json
from pathlib import Path

import pytest
from matplotlib.figure import Figure

import radar_core as core
import web_support


@pytest.mark.parametrize('radar_mode', ['RL-2000', 'PAR-NG', 'SSR'])
def test_quickreport_exports_every_available_flight_level_at_600dpi(monkeypatch, radar_mode):
    calls = []

    def fake_export_map(path, result, mode, *, dpi, levels_ft=(), **kwargs):
        assert dpi == 600
        calls.append((mode, tuple(levels_ft)))
        Path(path).write_bytes(b'fake-png-' + str(len(calls)).encode())

    monkeypatch.setattr(core, 'export_map_image', fake_export_map)
    monkeypatch.setattr(core, 'technical_plot', lambda fig, result: None)
    monkeypatch.setattr(Figure, 'savefig', lambda self, path, **kwargs: Path(path).write_bytes(b'fake-diagram'))

    result = {'config': SimpleNamespace(radar_mode=radar_mode),
              'completed_at': '2026-10-23T12:00:00Z', 'source': 'test DEM'}
    data = web_support.export_quickreport(result)
    with ZipFile(BytesIO(data)) as archive:
        names = archive.namelist()
        levels = core.flight_levels_for(radar_mode)
        images = sorted(x for x in names if x.endswith('.png'))
        assert len(images) == len(levels) + 2
        assert '01_Teren/terrain_600dpi.png' in names
        assert '02_Vyzarovaci_diagram/antenna_diagram_600dpi.png' in names
        assert 'README.txt' in names
        manifest = json.loads(archive.read('report_manifest.json'))
        assert manifest['flight_levels_ft_amsl'] == list(levels)
        assert manifest['image_dpi'] == 600
        for level in levels:
            name = f'03_Letove_hladiny/{level:05d}ft_AMSL_600dpi.png'
            assert name in names

        assert calls[0] == ('Terén', ())
        assert calls[1:] == [('Vybrané výšky', (level,)) for level in levels]


def test_quickreport_rejects_unsupported_levels():
    with pytest.raises(ValueError, match='Nepodporovaná'):
        web_support.export_quickreport({'config': SimpleNamespace(radar_mode='SSR')},
                                      flight_levels=[123456])
