"""Geodetic airport overlays and ICAO input regression tests."""
import pytest
from pyproj import Geod

from airport_geometry import (
    airport_runways, runway_geometry, par_bearing_for_runway,
    validate_icao, validate_saved_geometry,
)

GEOD = Geod(ellps="WGS84")


def fixture_rows():
    # Synthetic WGS84 north-south runway for deterministic tests; not AIP data.
    return [{
        "airport_ident":"TEST","id":"123","closed":"0",
        "le_ident":"18","he_ident":"36",
        "le_latitude_deg":"50.00","le_longitude_deg":"15.00",
        "he_latitude_deg":"49.98","he_longitude_deg":"15.00",
        "le_displaced_threshold_ft":"100",
        "he_displaced_threshold_ft":"0",
        "length_ft":"7300","width_ft":"150",
    }]


def test_icao_accepts_only_four_letters():
    assert validate_icao("lkpd") == "LKPD"
    for code in ("", "LKPD/", "https://example.com", "LKP2"):
        with pytest.raises(ValueError):
            validate_icao(code)


def test_runway_geometry_is_geodesic_and_keeps_displaced_threshold():
    runway = airport_runways("TEST", fixture_rows())[0]
    shapes = runway_geometry([runway], extension_nm=10)
    assert len(shapes) == 1
    assert shapes[0]["label"] == "18 / 36"
    assert len(shapes[0]["extended"]) == 4
    assert runway["thresholds"][0][0] < runway["ends"][0]["lat"]
    assert runway["midpoint"][0] < runway["ends"][0]["lat"]
    assert runway["midpoint"][0] > runway["ends"][1]["lat"]
    assert 178 < runway["heading_deg_true"] < 182
    assert not runway["verified_aip"]


def test_par_bearing_uses_selected_approach_side():
    runway = airport_runways("TEST", fixture_rows())[0]
    # Radar at the runway midpoint: approach to RWY 18 must be north of
    # the radar and approach to RWY 36 south of it.
    north=par_bearing_for_runway(runway, 0, 49.99, 15.0)
    south=par_bearing_for_runway(runway, 1, 49.99, 15.0)
    assert min(abs(north),abs(north-360)) < 1
    assert abs(south-180) < 1


def test_missing_endpoint_is_not_guessed():
    rows=fixture_rows()
    rows[0]["he_latitude_deg"]=""
    with pytest.raises(ValueError,match="souřadnice"):
        airport_runways("TEST",rows)


def test_saved_geometry_requires_valid_coordinates_and_source():
    runway=airport_runways("TEST",fixture_rows())[0]
    code,items=validate_saved_geometry("TEST",[runway])
    assert code=="TEST" and len(items)==1
    runway["midpoint"]=[900.,15.]
    with pytest.raises(ValueError):
        validate_saved_geometry("TEST",[runway])
