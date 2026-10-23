import numpy as np
import radar_core as core

def test_par_azimuth_sector_width_and_wrap():
    for bearing in (0, 90, 350):
        cfg = core.Config(radar_mode='PAR-NG', bearing_deg=bearing,
                          range_km=40, step_m=1000, az_step=1)
        az, _ = core.axes(cfg)
        assert len(az) == 31
        np.testing.assert_allclose((az[0], az[-1]), (bearing-15, bearing+15))
        indices, inside = core.azimuth_indices(az, cfg, [bearing-15, bearing, bearing+15, bearing+15.1, bearing-15.1])
        assert inside.tolist() == [True, True, True, False, False]

def test_par_low_flight_levels_only():
    par = core.flight_levels_for('PAR-NG')
    assert par[:4] == (50, 100, 150, 500)
    assert all(x in par for x in core.FLIGHT_LEVELS_LIST)
    assert core.flight_levels_for('RL-2000') == core.FLIGHT_LEVELS_LIST
    assert core.flight_levels_for('SSR') == core.FLIGHT_LEVELS_LIST
