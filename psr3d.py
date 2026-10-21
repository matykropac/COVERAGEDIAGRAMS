"""3 GHz 3D-PSR elevation cuts derived from supplied long/short CSV measurements.

The source exports contain one elevation sweep for one fixed LAZ cut. They
are not a complete 3D antenna pattern. For radial terrain coverage the cut
is assumed azimuth-invariant, an explicit modeling simplification.
"""
from pathlib import Path
import numpy as np
import radar_core as core

DATA_DIR = Path(__file__).resolve().parent / "data"
SOURCE_FILES = {
    "Short range": "3d_psr_short.csv",
    "Long range": "3d_psr_long.csv",
}

def load_3d_psr_cut(channel="Long range"):
    if channel not in SOURCE_FILES:
        raise ValueError("Unknown 3D PSR channel")
    source = DATA_DIR / SOURCE_FILES[channel]
    # Four semicolon-delimited columns: UAZ; UEL; LAZ; frequency-3000000000 gain.
    values = np.loadtxt(source, delimiter=";", skiprows=1, ndmin=2)
    if values.ndim != 2 or values.shape[1] != 4 or values.shape[0] < 500:
        raise ValueError("3D PSR CSV must contain four numeric columns and at least 500 samples")
    if not np.all(np.isfinite(values)):
        raise ValueError("3D PSR CSV contains nonfinite samples")
    if not np.allclose(values[:, 2], values[0, 2], atol=1e-3):
        raise ValueError("Expected a single LAZ cut, not a full azimuth scan")
    # UEL contains near-duplicate encoder angles. Aggregate into 0.1-degree
    # bins without assuming the sweep travels in a particular direction.
    degrees = np.round(values[:, 1], 1)
    angles = np.unique(degrees)
    gains = np.array([np.median(values[degrees == a, 3]) for a in angles])
    if len(angles) < 100 or np.any(np.diff(angles) <= 0):
        raise ValueError("3D PSR elevation sweep is invalid")
    gains -= np.max(gains)
    angles.setflags(write=False)
    gains.setflags(write=False)
    return core.AntennaPattern(
        f"3D LRR PSR · {channel} · 3 GHz · relative gain (LAZ {values[0,2]:+.3f}°)",
        angles,
        gains
    )
