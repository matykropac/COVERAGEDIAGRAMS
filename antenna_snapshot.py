"""Lossless, explicit serialization of antenna models for portable CDPROJ.

No pickle, arbitrary imports, or executable data are accepted. The exported
numeric grids are the *actual* models used in a calculation, not defaults.
"""
from dataclasses import fields
import numpy as np
import radar_core as core

_PREFIX = "antenna_"
_MAX_POINTS = 3_000_000


def _arr(value):
    out = np.asarray(value, dtype=np.float64)
    if not out.size or out.size > _MAX_POINTS or not np.isfinite(out).all():
        raise ValueError("Neplatné nebo příliš velké anténní pole.")
    return out


def pack(pattern):
    """Return (JSON-only metadata, array dict) without losing custom diagrams."""
    if pattern is None:
        return {"kind": "none"}, {}
    if isinstance(pattern, core.ParScanPattern):
        metadata = {f.name: getattr(pattern, f.name)
                    for f in fields(core.ParScanPattern)
                    if f.name not in ("angles_deg", "gains_db", "azimuths_deg", "gain_grid_db")}
        metadata["kind"] = "PAR"
        return metadata, {
            _PREFIX + "angles": _arr(pattern.angles_deg),
            _PREFIX + "gains": _arr(pattern.gains_db),
            _PREFIX + "azimuths": _arr(pattern.azimuths_deg),
            _PREFIX + "grid": _arr(pattern.gain_grid_db),
        }
    if isinstance(pattern, core.AntennaPatternPair):
        return {
            "kind": "DUAL", "name": pattern.name, "low_name": pattern.low.name,
            "high_name": pattern.high.name,
            "low_peak_dbi": float(pattern.low_peak_dbi),
            "high_peak_dbi": float(pattern.high_peak_dbi),
            "source_note": pattern.source_note,
        }, {
            _PREFIX + "low_angles": _arr(pattern.low.angles_deg),
            _PREFIX + "low_gains": _arr(pattern.low.gains_db),
            _PREFIX + "high_angles": _arr(pattern.high.angles_deg),
            _PREFIX + "high_gains": _arr(pattern.high.gains_db),
        }
    if isinstance(pattern, core.GenericSSRPattern):
        kind = "SSR"
    elif isinstance(pattern, core.AntennaPattern):
        kind = "SINGLE"
    else:
        raise ValueError("Neznámý typ anténního diagramu.")
    return {"kind": kind, "name": pattern.name}, {
        _PREFIX + "angles": _arr(pattern.angles_deg),
        _PREFIX + "gains": _arr(pattern.gains_db),
    }


def unpack(meta, arrays):
    """Restore only whitelisted, numerically validated pattern classes."""
    if not isinstance(meta, dict):
        raise ValueError("Neplatná metadata antény.")
    kind = meta.get("kind")
    required = {
        "none": set(),
        "PAR": {"angles", "gains", "azimuths", "grid"},
        "DUAL": {"low_angles", "low_gains", "high_angles", "high_gains"},
        "SSR": {"angles", "gains"},
        "SINGLE": {"angles", "gains"},
    }
    if kind not in required:
        raise ValueError("Nepodporovaný typ antény.")
    expected = {_PREFIX + key for key in required[kind]}
    if set(arrays) != expected:
        raise ValueError("V projektu chybí anténní data nebo obsahují neočekávaná pole.")
    data = {key[len(_PREFIX):]: _arr(value) for key, value in arrays.items()}
    for key in ("angles", "low_angles", "high_angles", "azimuths"):
        if key in data and (data[key].ndim != 1 or len(data[key]) < 2
                            or np.any(np.diff(data[key]) <= 0)):
            raise ValueError("Neplatná úhlová osa anténního diagramu.")
    if kind == "none":
        return None
    if kind in ("SSR", "SINGLE"):
        if data["angles"].shape != data["gains"].shape:
            raise ValueError("Neshoda úhlů a zisků antény.")
        cls = core.GenericSSRPattern if kind == "SSR" else core.AntennaPattern
        return cls(str(meta["name"]), data["angles"], data["gains"])
    if kind == "DUAL":
        for axis in ("low", "high"):
            if data[axis + "_angles"].shape != data[axis + "_gains"].shape:
                raise ValueError("Neshoda anténních dat LOW/HIGH.")
        low = core.AntennaPattern(str(meta["low_name"]),
                                  data["low_angles"], data["low_gains"])
        high = core.AntennaPattern(str(meta["high_name"]),
                                   data["high_angles"], data["high_gains"])
        return core.AntennaPatternPair(
            str(meta["name"]), low, high,
            float(meta["low_peak_dbi"]), float(meta["high_peak_dbi"]),
            str(meta.get("source_note", "")))
    if data["grid"].shape != (len(data["angles"]), len(data["azimuths"])):
        raise ValueError("Nesprávné rozměry 3D anténního diagramu.")
    if data["gains"].shape != data["angles"].shape:
        raise ValueError("Nesprávné rozměry řezu 3D diagramu.")
    kwargs = {f.name: meta[f.name] for f in fields(core.ParScanPattern)
              if f.name not in ("name", "angles_deg", "gains_db",
                                "azimuths_deg", "gain_grid_db")
              and f.name in meta}
    pattern = core.ParScanPattern(
        str(meta["name"]), data["angles"], data["gains"],
        data["azimuths"], data["grid"], **kwargs)
    pattern.validate_model()
    return pattern
