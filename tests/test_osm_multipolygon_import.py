"""Regressions for OSM multipolygon footprints and catalog integration."""
import math

from shapely.geometry import Polygon
from environment_layers import _overpass_relation_polygons, _simplify_ring
from geodata_obstacle_catalog import catalog_from_data, synchronize


def _member(role, coords, ref):
    return {"type": "way", "ref": ref, "role": role,
            "geometry": [{"lat": y, "lon": x} for x, y in coords]}


def test_split_outer_member_ways_assemble_into_polygon():
    outer = [(15.000, 50.000), (15.010, 50.000),
             (15.010, 50.010), (15.000, 50.010), (15.000, 50.000)]
    relation = {"members": [
        _member("outer", outer[:3], 1),
        _member("outer", outer[2:], 2),
    ]}
    polygons = _overpass_relation_polygons(relation)
    assert len(polygons) == 1
    assert len(polygons[0]) == 4
    assert Polygon([(lon, lat) for lat, lon in polygons[0]]).is_valid


def test_multipolygon_with_inner_hole_does_not_fill_hole():
    outer = [(15.0, 50.0), (15.02, 50.0), (15.02, 50.02),
             (15.0, 50.02), (15.0, 50.0)]
    inner = [(15.005, 50.005), (15.015, 50.005),
             (15.015, 50.015), (15.005, 50.015), (15.005, 50.005)]
    polygons = _overpass_relation_polygons({
        "members": [_member("outer", outer, 1), _member("inner", inner, 2)]
    })
    assert polygons
    result_area = sum(Polygon([(lon, lat) for lat, lon in ring]).area
                      for ring in polygons)
    assert abs(result_area - (0.02 * 0.02 - 0.01 * 0.01)) < 1e-10


def test_dense_osm_footprint_keeps_full_catalog_but_simplifies_solver_copy():
    dense = []
    for i in range(400):
        theta = 2 * math.pi * i / 400
        dense.append([50 + 0.001 * math.sin(theta),
                      15 + 0.001 * math.cos(theta)])
    reduced = _simplify_ring(dense, 150)
    assert reduced is not None and 3 <= len(reduced) <= 150
    source = [{"kind": "Building", "name": "Large OSM building",
               "source": "OpenStreetMap", "source_id": "way-1",
               "height_m": 18, "coordinates": dense}]
    catalog = catalog_from_data(source, [])
    assert len(catalog[0]["coordinates"]) == 400
    catalog[0]["enabled"] = True
    active, invalid = synchronize([], catalog, 50, 15)
    assert invalid == 0
    assert len(active) == 1
    assert len(active[0]["coordinates"]) <= 150
    assert len(catalog[0]["coordinates"]) == 400
