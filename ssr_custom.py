"""SSR vertical-cut patterns. Measured data remain distinct from RF budget assumptions."""
from pathlib import Path
import numpy as np
import radar_core as core


class MeasuredSSRPattern(core.GenericSSRPattern):
    """Measured elevation gain shape, interpreted as relative dB to its peak.

    The uploaded cut is reused on both 1030 and 1090 MHz links *as an assumption*
    because no separate 1030/1090 frequency cuts or absolute gain were supplied.
    """
    def gain_db(self, elevation_rad, tilt_deg=0.0):
        elevation_deg = np.rad2deg(np.asarray(elevation_rad)) - tilt_deg
        return np.interp(elevation_deg, self.angles_deg, self.gains_db,
                         left=-120., right=-120.)


def load_measured_ssr(path=None):
    path = Path(path) if path is not None else Path(__file__).resolve().parent / 'data' / 'SSR.txt'
    values = np.loadtxt(path, dtype=float, ndmin=2)
    if values.shape[1] != 2 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError('SSR: expected two finite columns (elevation degree, relative gain dB).')
    angles, gains = values.T
    if np.any(np.diff(angles) <= 0) or angles[0] > 0 or angles[-1] < 30:
        raise ValueError('SSR: elevation angles must strictly increase and cover 0–30°.')
    normalized = gains - gains.max()
    normalized.setflags(write=False)
    angles.setflags(write=False)
    return MeasuredSSRPattern('SSR.txt · measured vertical pattern (relative dB)',
                              angles, normalized)
