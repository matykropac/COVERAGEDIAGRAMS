"""Clockwise WGS84 arc model, backward compatibility and KML polygon serialization."""
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from pyproj import Geod

from obstacles import (arc_parameters, obstacle_polygon, obstacle_signature,
                       apply_obstacles, validate_obstacle)
import radar_core as core
from web_support import export_kml

GEOD = Geod(ellps='WGS84')


def arc_at(lat=50., lon=15., start=350., end=10., radius=250., height=80.):
    alon, alat, _ = GEOD.fwd(lon, lat, start, radius)
    blon, blat, _ = GEOD.fwd(lon, lat, end, radius)
    return dict(kind='arc', name='Výšková překážka', start_lat=alat, start_lon=alon,
                end_lat=blat, end_lon=blon, height_m=height)


def test_arc_clockwise_wraps_through_north():
    o = arc_at()
    b, span, r1, r2 = arc_parameters(o, 50., 15.)
    assert 349 < b < 351
    assert span == pytest.approx(20, abs=.1)
    assert r1 == pytest.approx(250, abs=.01)
    assert r2 == pytest.approx(250, abs=.01)
    poly = obstacle_polygon(o, 50., 15.)
    assert len(poly) >= 40


def test_arc_rejects_bad_endpoints_and_overlong_range():
    o = arc_at(start=45, end=45)
    with pytest.raises(ValueError, match='Úhlový'):
        validate_obstacle(o, 50., 15.)
    o = arc_at(radius=21000)
    with pytest.raises(ValueError, match='20 km'):
        validate_obstacle(o, 50., 15.)


def test_label_change_does_not_invalidate_physics():
    o = arc_at()
    changed = dict(o, name='Jiný název')
    assert obstacle_signature([o]) == obstacle_signature([changed])
    assert obstacle_signature([o]) != obstacle_signature([dict(o, height_m=100)])


def test_clockwise_arc_shadows_north_but_not_east():
    c = core.Config(lat=50., lon=15., antenna_agl=10., range_km=2.,
                    step_m=500., az_step=5., csc_enabled=False,
                    target_m=230., reference='AMSL')
    terrain, ground = core.demo_terrain(c)
    terrain[:] = 200.
    result = core.solve(c, terrain, 200.)
    north = int(np.argmin(np.abs(result['az'] - 0.)))
    east = int(np.argmin(np.abs(result['az'] - 90.)))
    n_before = result['status'][north].copy()
    e_before = result['status'][east].copy()
    apply_obstacles(result, [arc_at()])
    assert np.any(result['status'][north] < n_before)
    np.testing.assert_array_equal(result['status'][east], e_before, strict=True)


def test_kml_contains_folders_for_target_and_all_levels_and_obstacle_polygon(monkeypatch):
    import web_support
    geometry = {'type': 'Polygon', 'coordinates': [[
        [15., 50.], [15.01, 50.], [15.01, 50.01], [15., 50.]]]}
    monkeypatch.setattr(web_support, 'coverage_geojson',
                        lambda result, ft: {'features': [{'geometry': geometry}]})
    result = {'config': SimpleNamespace(lat=50., lon=15.),
              'obstacles': [dict(lat=50., lon=15.001, height_m=20.)]}
    data = export_kml(result, [100, 200, 500])
    xml = ET.fromstring(data)
    ns = {'k': 'http://www.opengis.net/kml/2.2'}
    folders = [node.text for node in xml.findall('.//k:Folder/k:name', ns)]
    assert folders == ['Krytí cíle', core.level_label(100),
                       core.level_label(200), core.level_label(500), 'Překážky']
    assert len(xml.findall('.//k:Polygon', ns)) == 5
    assert b'15.01000000,50.00000000,0' in data
