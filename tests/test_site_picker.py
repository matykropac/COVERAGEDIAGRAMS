"""Regression checks for map-to-radar-site WGS84 coordinates."""
import math

import pytest

from site_picker import coordinates_from_map_click


@pytest.mark.parametrize(
    ('click', 'expected'),
    [
        ({'lat': 50.034123456, 'lng': 15.781987654}, (50.034123, 15.781988)),
        ({'lat': -33.924869, 'lng': 18.424055}, (-33.924869, 18.424055)),
        ({'lat': 0, 'lng': 0}, (0.0, 0.0)),
        ({'lat': -80, 'lng': 180}, (-80.0, 180.0)),
    ],
)
def test_map_click_precise_wgs84_coordinates(click, expected):
    assert coordinates_from_map_click(click) == expected


@pytest.mark.parametrize(
    'click',
    [
        None,
        {},
        {'lat': 50.1},
        {'lng': 15.2},
        {'lat': math.nan, 'lng': 15.2},
        {'lat': 50.0, 'lng': math.inf},
        {'lat': 81, 'lng': 0},
        {'lat': -81, 'lng': 0},
        {'lat': 50, 'lng': 181},
        {'lat': 'wrong', 'lng': 15},
    ],
)
def test_map_click_rejects_invalid_or_out_of_bounds_coordinates(click):
    with pytest.raises(ValueError):
        coordinates_from_map_click(click)
