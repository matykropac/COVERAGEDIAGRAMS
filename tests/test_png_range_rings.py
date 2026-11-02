"""Regression tests for labelled 20 NM rings on all exported radar maps."""
from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
import pytest

import radar_core as core


@pytest.mark.parametrize("mode,expected", [
    ("RL-2000", list(range(20, 101, 20))),
    ("PSR", list(range(20, 101, 20))),
    ("SSR", list(range(20, 261, 20))),
    ("PAR-NG", []),
])
def test_range_rings_are_radar_centred_and_labelled(mode, expected):
    fig = Figure()
    ax = fig.add_subplot(111)
    c = SimpleNamespace(radar_mode=mode, range_km=60.0 if mode != "SSR" else 256 * 1.852)
    output = core.add_export_range_rings(ax, c)
    assert list(output) == expected
    assert [p.get_gid() for p in ax.patches] == [f"range-ring-{n}NM" for n in expected]
    assert [t.get_text() for t in ax.texts] == [f"{n} NM" for n in expected]
    for patch, nm in zip(ax.patches, expected):
        assert patch.center == (0, 0)
        assert patch.radius == pytest.approx(nm * 1.852)
    if expected:
        assert ax.get_xlim()[1] > expected[-1] * 1.852
        assert ax.get_ylim()[1] > expected[-1] * 1.852
