"""Runway reference geometry from public-domain OurAirports data.

OurAirports is indicative, NOT certified AIP threshold data.  AIP.aero is an
AIP directory, not a stable machine-readable endpoint-coordinate API.
Only documented HTTPS dataset URLs are contacted; airport codes are never
interpolated into URLs. No source credentials or arbitrary URL fetching.
"""
import csv
from datetime import datetime, timezone
from io import StringIO
import re
from urllib.request import Request, urlopen

from pyproj import Geod

RUNWAYS_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"
GEOD = Geod(ellps="WGS84")
MAX_CSV_BYTES = 10_000_000
FEET_TO_METRES = .3048


def validate_icao(icao):
    code = str(icao).strip().upper()
    if not re.fullmatch(r"[A-Z]{4}", code):
        raise ValueError("Zadej platný čtyřpísmenný kód ICAO.")
    return code


def runway_rows(download=None):
    """Download the public runway dataset; wrap in a 24h Streamlit cache in UI."""
    if download is None:
        def download(url):
            req = Request(url, headers={"User-Agent": "COVERAGEDIAGRAMS/1.0"})
            with urlopen(req, timeout=20) as response:
                payload = response.read(MAX_CSV_BYTES + 1)
            return payload
    data = download(RUNWAYS_URL)
    if len(data) > MAX_CSV_BYTES:
        raise ValueError("Zdroj geometrie RWY překročil bezpečnostní limit.")
    return list(csv.DictReader(StringIO(data.decode("utf-8-sig"))))


def _number(row, key):
    raw = row.get(key, "")
    if raw is None or not str(raw).strip():
        return None
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return None
    import math
    return value if math.isfinite(value) else None


def airport_runways(icao, rows):
    code = validate_icao(icao)
    result = []
    for row in rows:
        if str(row.get("airport_ident", "")).upper() != code or str(row.get("closed", "0")) == "1":
            continue
        points = []
        for prefix in ("le", "he"):
            lat = _number(row, prefix + "_latitude_deg")
            lon = _number(row, prefix + "_longitude_deg")
            ident = str(row.get(prefix + "_ident") or "").strip().upper()
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or not ident:
                break
            displaced = max(0., _number(row, prefix + "_displaced_threshold_ft") or 0.)
            points.append(dict(lat=lat, lon=lon, ident=ident, displaced_m=displaced * FEET_TO_METRES))
        if len(points) != 2:
            continue
        left, right = points
        heading, reverse, length_m = GEOD.inv(left["lon"], left["lat"], right["lon"], right["lat"])
        if length_m < 30 or length_m > 10000:
            continue
        declared_length = _number(row, "length_ft")
        # Endpoint centers (from the dataset) are NOT always physical thresholds.
        # Displaced-threshold offsets move from the runway end toward the other end.
        def displaced_point(point, az, offset):
            lon, lat, _ = GEOD.fwd(point["lon"], point["lat"], az, min(offset, length_m * .49))
            return [float(lat), float(lon)]
        first_threshold = displaced_point(left, heading, left["displaced_m"])
        second_threshold = displaced_point(right, reverse, right["displaced_m"])
        midpoint_lon, midpoint_lat, _ = GEOD.fwd(left["lon"], left["lat"], heading, length_m / 2)
        result.append({
            "key": str(row.get("id") or left["ident"] + "-" + right["ident"]),
            "label": left["ident"] + " / " + right["ident"],
            "length_m": float(declared_length * FEET_TO_METRES if declared_length else length_m),
            "geodesic_length_m": float(length_m),
            "width_m": (_number(row, "width_ft") or 0) * FEET_TO_METRES,
            "heading_deg_true": float(heading % 360),
            "ends": [left, right],
            "thresholds": [first_threshold, second_threshold],
            "midpoint": [float(midpoint_lat), float(midpoint_lon)],
            "source": "OurAirports public-domain runways.csv",
            "verified_aip": False,
        })
    if not result:
        raise ValueError(
            f"Pro {code} nejsou dostupné obě souřadnice konců RWY. "
            "Nelze bezpečně vymyslet osu; ověř údaje v oficiálním AIP.")
    return result


def runway_geometry(runways, *, extension_nm=10):
    """Leaflet-ready drawing primitives (WGS84 lat/lon), no synthetic coordinates."""
    shapes = []
    extension_m = float(extension_nm) * 1852
    for runway in runways:
        a, b = runway["ends"]
        left, right = [a["lat"], a["lon"]], [b["lat"], b["lon"]]
        bearing = runway["heading_deg_true"]
        start_lon, start_lat, _ = GEOD.fwd(a["lon"], a["lat"], bearing + 180, extension_m)
        end_lon, end_lat, _ = GEOD.fwd(b["lon"], b["lat"], bearing, extension_m)
        shapes.append(dict(
            label=runway["label"], centerline=[left, right],
            extended=[[float(start_lat), float(start_lon)], left, right, [float(end_lat), float(end_lon)]],
            thresholds=runway["thresholds"], midpoint=runway["midpoint"],
            true_bearing=round(bearing, 2), width_m=runway["width_m"],
        ))
    return shapes


def par_bearing_for_runway(runway, selected_end, radar_lat, radar_lon, *, lookahead_nm=5):
    """Radar-to-approach-corridor bearing, not the magnetic RWY heading.

    The PAR station can be laterally displaced.  Point the bore sight toward a
    point on the extended approach axis 5 NM before the selected threshold.
    """
    idx = int(selected_end)
    if idx not in (0, 1):
        raise ValueError("Vyber práh konkrétní RWY.")
    threshold = runway["thresholds"][idx]
    opposite = runway["thresholds"][1 - idx]
    runway_inbound, _, _ = GEOD.inv(threshold[1], threshold[0], opposite[1], opposite[0])
    approach_outbound = (runway_inbound + 180) % 360
    lon, lat, _ = GEOD.fwd(threshold[1], threshold[0], approach_outbound, lookahead_nm * 1852)
    bearing, _, _ = GEOD.inv(float(radar_lon), float(radar_lat), lon, lat)
    return float(bearing % 360)


def validate_saved_geometry(icao, runways):
    """Reject malformed untrusted project metadata before drawing it."""
    code = validate_icao(icao)
    if not isinstance(runways, list) or len(runways) > 40:
        raise ValueError("Neplatný počet RWY v projektu.")
    validated = []
    for item in runways:
        if not isinstance(item, dict) or item.get("source") != "OurAirports public-domain runways.csv":
            raise ValueError("Neplatný zdroj geometrie RWY.")
        ends = item.get("ends")
        thresholds = item.get("thresholds")
        midpoint = item.get("midpoint")
        if not isinstance(ends, list) or len(ends) != 2 or not isinstance(thresholds, list) or len(thresholds) != 2:
            raise ValueError("Neplatné prahy RWY.")
        for endpoint in ends:
            if not isinstance(endpoint, dict) or not isinstance(endpoint.get("ident"), str) or len(endpoint["ident"]) > 5:
                raise ValueError("Neplatné označení RWY.")
            _validate_point([endpoint.get("lat"), endpoint.get("lon")])
        for point in thresholds + [midpoint]:
            _validate_point(point)
        heading = float(item.get("heading_deg_true", -1))
        if not 0 <= heading < 360:
            raise ValueError("Neplatný zeměpisný azimut dráhy.")
        validated.append(item)
    return code, validated


def _validate_point(point):
    import math
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        raise ValueError("Neplatné souřadnice RWY.")
    lat, lon = (float(value) for value in point)
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Neplatné zeměpisné souřadnice RWY.")
