"""Optional, read-only ADS-B traffic overlay for the OBSTACLES map.

Traffic is informational and never enters terrain/obstacle coverage calculations.
Data source: adsb.lol public readsb-compatible API (ODbL 1.0).
"""
import csv
from datetime import datetime, timezone
from io import StringIO
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import folium
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
FIELDS = ("timestamp_utc", "icao24", "callsign", "lat", "lon",
          "altitude_ft", "altitude_m", "groundspeed_kt", "track_deg", "source")


def fetch_snapshot(lat, lon, radius_nm=100, *, timeout=12):
    """One explicit user-triggered request; no background polling or API keys."""
    radius_nm = max(1, min(250, int(radius_nm)))
    url = f"https://api.adsb.lol/v2/point/{float(lat):.5f}/{float(lon):.5f}/{radius_nm}"
    req = Request(url, headers={
        "User-Agent": "COVERAGEDIAGRAMS/1.0 (educational radar coverage map)",
        "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"ADS-B server není dostupný ({type(exc).__name__}).") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("ac"), list):
        raise ValueError("ADS-B server vrátil neočekávaný formát.")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = []
    for item in payload["ac"]:
        try:
            la, lo = float(item["lat"]), float(item["lon"])
            if not (-90 <= la <= 90 and -180 <= lo <= 180):
                continue
            _, _, distance = GEOD.inv(float(lon), float(lat), lo, la)
            if distance > radius_nm * 1852:
                continue
            # Skip stale reports; present this layer as a recent snapshot, not a track.
            seen = item.get("seen_pos")
            if seen is not None and float(seen) > 120:
                continue
            alt = item.get("alt_geom")
            if alt is None:
                alt = item.get("alt_baro")
            if alt in (None, "ground"):
                altitude_ft = None
            else:
                altitude_ft = float(alt)
            gs = item.get("gs")
            track = item.get("track")
            records.append({
                "timestamp_utc": timestamp,
                "icao24": str(item.get("hex") or ""),
                "callsign": str(item.get("flight") or "").strip(),
                "lat": la, "lon": lo,
                "altitude_ft": altitude_ft,
                "altitude_m": round(altitude_ft * .3048, 1) if altitude_ft is not None else None,
                "groundspeed_kt": float(gs) if gs is not None else None,
                "track_deg": float(track) if track is not None else None,
                "source": "adsb.lol (ODbL 1.0)",
            })
        except (TypeError, ValueError, KeyError):
            continue
    return records


def add_traffic_layer(map_obj, records):
    """Render one compact toggleable overlay, no individual LayerControl entries."""
    group = folium.FeatureGroup(name=f"ADS-B provoz · {len(records)} pozic", show=True)
    for ac in records:
        altitude = ac.get("altitude_ft")
        alt_label = f"{altitude:,.0f} ft" if altitude is not None else "výška neznámá"
        callsign = ac.get("callsign") or ac.get("icao24") or "Unknown"
        label = f"{callsign} · {alt_label}"
        folium.CircleMarker(
            [ac["lat"], ac["lon"]], radius=3, weight=1,
            color="#27c5f5", fill=True, fill_color="#27c5f5",
            fill_opacity=.85, tooltip=label,
        ).add_to(group)
    group.add_to(map_obj)


def traffic_csv(records):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue().encode("utf-8-sig")
