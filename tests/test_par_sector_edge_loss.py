"""Regression tests for the smooth PAR ±15° sector-edge attenuation."""
import numpy as np
from par_scan_engine import evaluate


class FlatPattern:
    coverage_mode = "ENGINEERING"
    channel_mode = "BOTH"
    gas_loss_db_per_km = 0.0
    rain_loss_db_per_km = 0.0
    additional_loss_db = 0.0
    sector_edge_loss_db = 6.0

    def validate_model(self):
        return None

    def channel_range_factors(self, elevation_rad, azimuth_deg, tilt_deg):
        az = np.asarray(azimuth_deg, dtype=float)
        return np.ones_like(az), np.ones_like(az)


def test_par_sector_edge_attenuation_symmetric():
    angles = np.array([-15., -7.5, 0., 7.5, 15.])
    out = evaluate(FlatPattern(), np.zeros_like(angles), angles,
                   np.full_like(angles, 40000.), reference_range_km=40.)
    expected = np.array([-6., -1.5, 0., -1.5, -6.])
    np.testing.assert_allclose(out["az_margin_db"], expected, atol=1e-9)
    np.testing.assert_allclose(out["el_margin_db"], expected, atol=1e-9)
    assert list(out["selected"]) == [False, False, True, False, False]


def test_par_edge_range_reduction():
    pattern = FlatPattern()
    shortened_km = 40. * 10.**(-6./40.)
    out = evaluate(pattern, 0., 15., shortened_km*1000., reference_range_km=40.)
    assert abs(float(out["limiting_margin_db"])) < 1e-8
    assert 28. < shortened_km < 29.

def test_three_db_comparison_scenario():
    pattern = FlatPattern()
    pattern.sector_edge_loss_db = 3.0
    angles = np.array([-15., -7.5, 0., 7.5, 15.])
    out = evaluate(pattern, np.zeros_like(angles), angles,
                   np.full_like(angles, 40000.), reference_range_km=40.)
    np.testing.assert_allclose(out["limiting_margin_db"],
                               [-3., -.75, 0., -.75, -3.], atol=1e-9)
    np.testing.assert_allclose(out["sector_edge_loss_db"],
                               [3., .75, 0., .75, 3.], atol=1e-9)
