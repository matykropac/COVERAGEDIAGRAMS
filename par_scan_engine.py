"""PAR AESA scan acceleration and channel diagnostics.

The antenna scan is independent of DEM sampling. FAST interpolates a bounded,
precomputed azimuth/elevation lookup table; ENGINEERING evaluates the selected
scan positions directly. Both paths use the same antenna forward model.

This is NOT a calibrated radar equation. The AZ source grid has unconfirmed
antenna attribution; EL gain is an analytic placeholder pending its real grid.
Atmospheric coefficients are user assumptions; terrain is currently LOS only.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import RLock

import numpy as np

_CACHE = OrderedDict()
_CACHE_LOCK = RLock()
_MAX_ENTRIES = 8
_AZ_AXIS = np.linspace(-15., 15., 301, dtype=np.float64)
_EL_AXIS = np.linspace(-5., 89., 471, dtype=np.float64)


def _signature(pattern, tilt_deg):
    return (
        pattern.source_sha256, pattern.scan_mode,
        pattern.channel_mode, pattern.steering_loss_db_per_deg,
        pattern.detection_model, pattern.reference_snr_db,
        pattern.pd, pattern.pfa, pattern.pulses,
        pattern.az_beam_step_deg, pattern.el_beam_step_deg,
        float(tilt_deg),
    )


def _scan_lut(pattern, tilt_deg):
    key = _signature(pattern, tilt_deg)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached
    az_grid, el_grid = np.meshgrid(_AZ_AXIS, _EL_AXIS)
    az_factor, el_factor = pattern.channel_range_factors(
        np.deg2rad(el_grid), az_grid, tilt_deg)
    values = (
        np.asarray(az_factor, dtype=np.float32),
        np.asarray(el_factor, dtype=np.float32),
    )
    for value in values:
        value.flags.writeable = False
    with _CACHE_LOCK:
        _CACHE[key] = values
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_ENTRIES:
            _CACHE.popitem(last=False)
    return values


def _interpolate_grid(grid, elevation_deg, azimuth_deg):
    el, az = np.broadcast_arrays(np.asarray(elevation_deg, dtype=float),
                                 np.asarray(azimuth_deg, dtype=float))
    ei = np.searchsorted(_EL_AXIS, el, side="right")-1
    ai = np.searchsorted(_AZ_AXIS, az, side="right")-1
    ei = np.clip(ei, 0, len(_EL_AXIS)-2)
    ai = np.clip(ai, 0, len(_AZ_AXIS)-2)
    er = np.clip((el-_EL_AXIS[ei])/(_EL_AXIS[ei+1]-_EL_AXIS[ei]), 0., 1.)
    ar = np.clip((az-_AZ_AXIS[ai])/(_AZ_AXIS[ai+1]-_AZ_AXIS[ai]), 0., 1.)
    out = (grid[ei, ai]*(1-er)*(1-ar)
           + grid[ei+1, ai]*er*(1-ar)
           + grid[ei, ai+1]*(1-er)*ar
           + grid[ei+1, ai+1]*er*ar)
    valid = (np.isfinite(el)&np.isfinite(az)&
             (el>=_EL_AXIS[0])&(el<=_EL_AXIS[-1])&
             (az>=_AZ_AXIS[0])&(az<=_AZ_AXIS[-1]))
    return np.where(valid, out, 1e-12)


def channel_factors(pattern, elevation_rad, azimuth_deg, tilt_deg=0.):
    """Evaluate the same channel response with or without reusable LUT."""
    if pattern.coverage_mode == "ENGINEERING":
        return pattern.channel_range_factors(
            elevation_rad, azimuth_deg, tilt_deg)
    az, el = _scan_lut(pattern, tilt_deg)
    degrees = np.rad2deg(elevation_rad)
    return (_interpolate_grid(az, degrees, azimuth_deg),
            _interpolate_grid(el, degrees, azimuth_deg))


def evaluate(pattern, elevation_rad, azimuth_deg, slant_range_m, *,
             tilt_deg=0., reference_range_km=40.):
    """Return per-channel masks and normalized margins.

    Atmospheric loss is a two-way, user-defined dB/km coefficient applied
    per actual slant range. The reach calculation is an engineering scenario
    and does not imply known RF noise, target RCS, clutter or certified Pd.

    Positive margin = target inside the assumed normalized range envelope.
    """
    pattern.validate_model()
    az_factor, el_factor = channel_factors(
        pattern, elevation_rad, azimuth_deg, tilt_deg)
    distance_km = np.asarray(slant_range_m, dtype=float)/1000.
    loss_one_way = (pattern.gas_loss_db_per_km+
                    pattern.rain_loss_db_per_km)*distance_km
    # A normalized monostatic radar uses 40*log10(Rref/R), with
    # reference Rref=40 km. Round-trip attenuation is 2*L(one-way).
    # Factors already include the signal response in their R/Rref ratio.
    safe_distance = np.maximum(distance_km, 1e-6)
    range_margin = 40.*np.log10(reference_range_km/safe_distance)
    extra_loss_db = 2.*loss_one_way + pattern.additional_loss_db
    # Scenario-only symmetric quadratic sector taper (not measured antenna gain).
    # Applied once to link margin for each separately evaluated channel.
    azimuth = np.asarray(azimuth_deg, dtype=float)
    edge_loss_db = float(getattr(pattern, "sector_edge_loss_db", 6.0)) * (
        np.clip(np.abs(azimuth) / 15.0, 0.0, 1.0) ** 2
    )
    extra_loss_db = extra_loss_db + edge_loss_db
    with np.errstate(divide="ignore", invalid="ignore"):
        margin_az = (range_margin+
                     40.*np.log10(np.maximum(az_factor, 1e-12))-
                     extra_loss_db)
        margin_el = (range_margin+
                     40.*np.log10(np.maximum(el_factor, 1e-12))-
                     extra_loss_db)
    instrumented = np.isfinite(distance_km) & (distance_km <= reference_range_km)
    az_ok = instrumented & (margin_az >= -1e-7)
    el_ok = instrumented & (margin_el >= -1e-7)
    if pattern.channel_mode == "AZ":
        selected = az_ok
        limiting = margin_az
    elif pattern.channel_mode == "EL":
        selected = el_ok
        limiting = margin_el
    else:
        selected = az_ok & el_ok
        limiting = np.minimum(margin_az, margin_el)
    return dict(az=az_ok, el=el_ok, both=az_ok & el_ok,
                selected=selected,
                az_margin_db=margin_az, el_margin_db=margin_el,
                limiting_margin_db=limiting,
                sector_edge_loss_db=edge_loss_db,
                limiting_channel=np.where(margin_az <= margin_el, 0, 1))


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()
