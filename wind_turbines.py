"""Read-only wind turbine map layer from OpenStreetMap / Overpass."""
import math
import urllib.parse
import urllib.request

import folium
import streamlit as st
from folium.plugins import MarkerCluster
from pyproj import Geod
from wind_offline import select_turbines, bundled_dataset

GEOD = Geod(ellps="WGS84")
RADIUS_M = 100_000
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


@st.cache_data(ttl=86400, show_spinner=False)
def load_wind_turbines(lat: float, lon: float):
    """Prefer bundled/uploaded offline dataset; Overpass only when none is available."""
    raw = st.session_state.get("wind_dataset_bytes")
    filename = st.session_state.get("wind_dataset_filename", "wind_turbines.csv")
    if raw is None:
        raw = bundled_dataset()
        filename = "wind_turbines.csv.gz"
    if raw is not None:
        return select_turbines(raw, filename, lat, lon, RADIUS_M)
    import json
    # A bounding box is much cheaper for Overpass than a 100 km around query.
    lat_delta = RADIUS_M / 111_000
    lon_delta = RADIUS_M / (111_000 * max(0.1, math.cos(math.radians(lat))))
    south, north = max(-90, lat-lat_delta), min(90, lat+lat_delta)
    west, east = max(-180, lon-lon_delta), min(180, lon+lon_delta)
    bbox = f"{south:.5f},{west:.5f},{north:.5f},{east:.5f}"
    query = (
        '[out:json][timeout:20];'
        f'node["power"="generator"]["generator:source"="wind"]({bbox});'
        'out body;'
    )
    import json
    errors = []
    for endpoint in (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.nchc.org.tw/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ):
        try:
            url = endpoint + "?" + urllib.parse.urlencode({"data": query})
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 COVERAGEDIAGRAMS"})
            with urllib.request.urlopen(req, timeout=12) as response:
                raw = json.load(response)
            break
        except Exception as exc:
            errors.append(f"{urllib.parse.urlsplit(endpoint).hostname}: {type(exc).__name__}: {exc}")
    else:
        raise RuntimeError(" | ".join(errors))
    turbines = []
    seen = set()
    for element in raw.get("elements", []):
        tags = element.get("tags", {})
        # Avoid counting wind farm polygons and generic wind-powered objects.
        if tags.get("power") not in ("generator", None):
            continue
        point = element.get("center", element)
        plat, plon = point.get("lat"), point.get("lon")
        if plat is None or plon is None:
            continue
        identity = (element.get("type"), element.get("id"))
        if identity in seen:
            continue
        seen.add(identity)
        az, _, distance = GEOD.inv(lon, lat, plon, plat)
        if not math.isfinite(distance) or distance > RADIUS_M:
            continue
        turbines.append({
            "lat": float(plat), "lon": float(plon), "az": round(az % 360, 1),
            "distance_km": round(distance / 1000, 2),
            "name": tags.get("name") or f"Turbína OSM #{element.get('id')}",
            "height": tags.get("height") or tags.get("tower:height") or tags.get("generator:height"),
            "hub_height": tags.get("generator:hub_height") or tags.get("hub:height"),
            "rotor": tags.get("rotor:diameter") or tags.get("generator:rotor:diameter"),
            "osm_id": str(element.get("id", "")),
        })
    return turbines


def add_wind_layer(map_obj, turbines, cluster_points=True, fallback_height=None):
    from html import escape
    layer = folium.FeatureGroup(name=f"Větrné turbíny ({len(turbines)})", show=True)
    target = layer
    if cluster_points:
        target = MarkerCluster(name="Větrné turbíny", options={"maxClusterRadius": 45, "disableClusteringAtZoom": 12})
        target.add_to(layer)
    for t in turbines:
        height = t["height"]
        if not height and fallback_height is not None:
            height = f"{fallback_height:g} m (uživatelský předpoklad)"
        fields = [
            ("Vzdálenost", f"{t['distance_km']} km"),
            ("Azimut", f"{t['az']}°"),
            ("Výška", str(height) if height else "nezjištěna"),
            ("Výška náboje", str(t["hub_height"]) if t["hub_height"] else "nezjištěna"),
            ("Průměr rotoru", str(t["rotor"]) if t["rotor"] else "nezjištěn"),
            ("OSM ID", t["osm_id"]),
        ]
        body = "<b>" + escape(t["name"]) + "</b><br>" + "<br>".join(
            f"{escape(k)}: {escape(v)}" for k, v in fields
        ) + "<br><small>Informační vrstva OSM · není automaticky překážkou.</small>"
        folium.CircleMarker(
            [t["lat"], t["lon"]], radius=5, color="#f8e07b", weight=1.5,
            fill=True, fill_color="#f59e0b", fill_opacity=.95,
            tooltip=escape(t["name"]), popup=folium.Popup(body, max_width=320),
        ).add_to(target)
    layer.add_to(map_obj)
