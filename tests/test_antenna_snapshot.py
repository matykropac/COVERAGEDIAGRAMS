"""Round-trip fidelity of site-specific antenna data and calculations."""
import numpy as np
import pytest
import radar_core as core
from antenna_snapshot import pack, unpack
from project_file import save_project, load_project


def _roundtrip(pattern):
    meta, arrays = pack(pattern)
    restored = unpack(meta, arrays)
    return restored


def test_dual_psr_site_pattern_survives():
    low = core.AntennaPattern("measured-low",
                              np.array([-2., 0., 10.]), np.array([-3., 0., -12.]))
    high = core.AntennaPattern("measured-high",
                               np.array([-2., 0., 10.]), np.array([-15., -2., 0.]))
    original = core.AntennaPatternPair("site-PSR", low, high, 34.3, 33.3)
    restored = _roundtrip(original)
    assert restored.name == original.name
    np.testing.assert_array_equal(restored.low.gains_db, original.low.gains_db)
    np.testing.assert_array_equal(restored.high.gains_db, original.high.gains_db)
    np.testing.assert_allclose(
        restored.range_factor(np.deg2rad([0., 4.])),
        original.range_factor(np.deg2rad([0., 4.])),
    )


def test_par_scan_model_survives():
    original = core.builtin_par_pattern()
    restored = _roundtrip(original)
    assert restored.source_sha256 == original.source_sha256
    assert restored.sector_edge_loss_db == original.sector_edge_loss_db
    np.testing.assert_array_equal(restored.gain_grid_db, original.gain_grid_db)


def test_ssr_transponder_model_survives():
    original = core.generic_ssr_pattern()
    restored = _roundtrip(original)
    assert isinstance(restored, core.GenericSSRPattern)
    np.testing.assert_array_equal(restored.angles_deg, original.angles_deg)


def test_reject_missing_antenna_grid():
    original = core.builtin_par_pattern()
    meta, arrays = pack(original)
    arrays.pop("antenna_grid")
    with pytest.raises(ValueError):
        unpack(meta, arrays)
