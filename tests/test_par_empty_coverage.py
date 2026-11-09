"""Regression tests for a PAR calculation that finishes with an empty map."""
import numpy as np

import radar_core as core
from web_support import coverage_diagnostic, coverage_diagnostic_message


def _flat_result():
    config = core.Config(
        radar_mode="PAR-NG", range_km=40, csc_range_km=40,
        step_m=1000, az_step=1, min_elev=-1, max_elev=10,
        csc_enabled=True, antenna_tilt_deg=0)
    az, ranges = core.axes(config)
    terrain = np.zeros((len(az), len(ranges)), dtype=float)
    return core.solve(config, terrain, 0.0, core.builtin_par_pattern())


def test_empty_layer_is_diagnosed_without_claiming_no_coverage():
    result = _flat_result()
    diagnostics = coverage_diagnostic(result, 3000, [])
    assert diagnostics["known"] == result["terrain"].size
    assert diagnostics["geometric"] >= diagnostics["covered"]
    assert diagnostics["features"] == 0
    if diagnostics["covered"] > 0:
        assert "vektorizaci" in coverage_diagnostic_message(diagnostics)


def test_low_amsl_level_below_site_is_not_claimed_as_renderer_bug():
    result = _flat_result()
    result["terrain"][:] = 800.0
    result["lower"][:] = 800.0
    diagnostics = coverage_diagnostic(result, 50, [])
    assert diagnostics["geometric"] == 0
    assert "AMSL" in coverage_diagnostic_message(diagnostics)


def test_missing_dem_is_reported_before_antenna_limit():
    result = _flat_result()
    result["known"][:] = False
    diagnostics = coverage_diagnostic(result, 3000, [])
    assert diagnostics["known"] == 0
    assert "DEM" in coverage_diagnostic_message(diagnostics)
