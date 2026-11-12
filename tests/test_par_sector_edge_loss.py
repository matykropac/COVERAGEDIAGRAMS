"""Regression tests for the smooth PAR ±15° sector-edge attenuation."""
import numpy as np
from par_scan_engine import evaluate


class FlatPattern:
    coverage_mode = "ENGINEERING"
    channel_mode = "BOTH"
    gas_loss_db_per_km = 0.0
    rain_loss_db_per_km = 0.0
    additional_loss_db = 0.0

    def validate_model(self):
        return None

    def channel_range_factors(self, elevation_rad, azimuth_deg, tilt_deg):
        az = np.asarray(azimuth_deg, dtype=float)
        return np.ones_like(az), np.ones_like(az)


def test_par_sector_edge_attenuation_symmetric():
    angles = np.array([-15., -7.5, 0., 7.5, 15.])
    out = evaluate(FlatPattern(), np.zeros_like(angles), angles,
                   np.full_like(angles, 40000.), reference_range_km=40.)
    expected = np.array([-1.5, -0.75, 0., -0.75, -1.5])
    np.testing.assert_allclose(out["az_margin_db"], expected, atol=1e-9)
    np.testing.assert_allclose(out["el_margin_db"], expected, atol=1e-9)
    assert list(out["selected"]) == [False, False, True, False, False]


def test_par_edge_range_reduction():
    pattern = FlatPattern()
    shortened_km = 40. * 10.**(-1.5/40.)
    out = evaluate(pattern, 0., 15., shortened_km*1000., reference_range_km=40.)
    assert abs(float(out["limiting_margin_db"])) < 1e-8
    assert 36. < shortened_km < 37.
