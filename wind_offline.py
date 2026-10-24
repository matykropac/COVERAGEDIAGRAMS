"""Offline wind turbine dataset parser (CSV / GeoJSON exports)."""
import csv
import io
import json
import math
from pathlib import Path

from pyproj import Geod

_GEOD = Geod(ellps="WGS84")
_LOCAL = Path(__file__).resolve().parent / "data" / "wind_turbines.csv"


def _pick(record, *keys):
    normalized = {str(k).lower().replace("_", "").replace(" ", ""): v
                  for k, v in record.items()}
    for key in keys:
        val = normalized.get(key.lower().replace("_", "").replace(" ", ""))
        if val is not None and str(val).strip():
            return val
    return None


def _number(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(" m", "").strip())
    except (ValueError, TypeError):
        return None


def _records(raw, filename):
    if filename.lower().endswith((".geojson", ".json")):
        data = json.loads(raw.decode("utf-8-sig"))
        for feature in data.get("features", []):
            if feature.get("geometry", {}).get("type") != "Point":
                continue
            coords = feature["geometry"].get("coordinates", [])
            if len(coords) >= 2:
                yield dict(feature.get("properties") or {}, lon=coords[0], lat=coords[1])
    else:
        yield from csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))


def select_turbines(raw, filename, lat, lon, radius_m=100_000):
    turbines = []
    seen = set()
    for row in _records(raw, filename):
        plat = _number(_pick(row, "lat", "latitude", "y"))
        plon = _number(_pick(row, "lon", "lng", "longitude", "x"))
        if plat is None or plon is None or not (-90 <= plat <= 90 and -180 <= plon <= 180):
            continue
        az, _, dist = _GEOD.inv(lon, lat, plon, plat)
        if not math.isfinite(dist) or dist > radius_m:
            continue
        identity = (round(plat, 6), round(plon, 6))
        if identity in seen:
            continue
        seen.add(identity)
        hub = _number(_pick(row, "hub_height", "hubheight", "generator:hub_height"))
        rotor = _number(_pick(row, "rotor_diameter", "rotordiameter", "rotor:diameter"))
        total = _number(_pick(row, "height", "total_height", "tip_height"))
        if total is None and hub is not None and rotor is not None:
            total = hub + rotor / 2
        turbines.append(dict(
            lat=plat, lon=plon, az=round(az % 360, 1),
            distance_km=round(dist / 1000, 2),
            name=str(_pick(row, "name", "model", "id") or "Větrná turbína"),
            height=f"{total:g} m" if total is not None else None,
            hub_height=f"{hub:g} m" if hub is not None else None,
            rotor=f"{rotor:g} m" if rotor is not None else None,
            osm_id=str(_pick(row, "id", "osm_id", "source_id") or ""),
        ))
    return turbines


def bundled_dataset():
    return _LOCAL.read_bytes() if _LOCAL.is_file() else None
