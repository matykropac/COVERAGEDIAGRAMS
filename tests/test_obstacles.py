import numpy as np
from types import SimpleNamespace
from obstacles import intersection, square_corners, apply_obstacles
from radar_core import Config, demo_terrain, solve

def test_square_has_four_geodetic_corners():
    assert len(square_corners(50., 15.)) == 4

def test_ten_m_square_intersection():
    assert intersection(90., 100., 0.) == (95., 105.)
    assert intersection(0., 100., 0.) is None

def test_obstacle_between_sparse_samples_blocks_target():
    c = Config(lat=50., lon=15., antenna_agl=10., range_km=2.,
               step_m=500., az_step=5., csc_enabled=False,
               target_m=230., reference='AMSL')
    terrain, ground = demo_terrain(c)
    # Flat known terrain isolates horizon effect.
    terrain[:] = 200.
    result = solve(c, terrain, 200.)
    bearing = 90.
    from pyproj import Geod
    lon,lat,_ = Geod(ellps='WGS84').fwd(c.lon,c.lat,bearing,250.)
    j = int(np.argmin(np.abs(result['az']-90.)))
    before = result['status'][j].copy()
    apply_obstacles(result,[dict(lat=lat,lon=lon,height_m=80.)])
    assert np.any(result['status'][j] < before)
    assert result['horizon'][j,0] > -np.inf
    assert len(result['obstacles']) == 1

def test_no_obstacles_does_not_change_status():
    c=Config(range_km=2.,step_m=500.,az_step=5.,csc_enabled=False)
    terrain,ground=demo_terrain(c)
    result=solve(c,terrain,ground)
    old=result['status'].copy()
    apply_obstacles(result, [])
    np.testing.assert_array_equal(result['status'],old)
