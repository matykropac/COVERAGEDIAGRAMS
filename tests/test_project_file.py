import io
from zipfile import ZipFile
import numpy as np
import pytest
import radar_core as core
from project_file import save_project, load_project

def test_roundtrip_project_with_numeric_matrices_and_low_flight_levels():
    c = core.Config(radar_mode='PAR-NG', range_km=40, csc_range_km=40,
                    az_step=2, step_m=2000)
    az, dist = core.axes(c)
    shape = (len(az), len(dist))
    result = {key: (az if key == 'az' else dist if key == 'distance'
                    else np.ones(shape, dtype=bool) if key == 'known'
                    else np.full(shape, 150., dtype=float))
              for key in ('az','distance','terrain','lower','upper','status','target','horizon','known')}
    result.update(config=c, antenna=220., site_height=200., source='test',
                  completed_at='2026-10-23', duration_s=1.0)
    obstacles = [{'lat':50.0,'lon':15.0,'height_m':12.}]
    blob = save_project(result, levels=[50, 250, 500], obstacles=obstacles)
    loaded, metadata = load_project(blob)
    assert metadata['levels'] == [50,250,500]
    assert loaded['obstacles'] == obstacles
    assert loaded['config'] == c
    assert loaded['known'].dtype == bool
    np.testing.assert_array_equal(loaded['terrain'], result['terrain'])

def test_invalid_project_rejected():
    with pytest.raises(ValueError):
        load_project(b'not a project')
    archive = io.BytesIO()
    with ZipFile(archive, 'w') as z:
        z.writestr('evil.py', 'print(1)')
    with pytest.raises(ValueError):
        load_project(archive.getvalue())
