"""Optional airport reference layer from OurAirports open CSV (not obstacle certification)."""
import csv
import json
import io
import urllib.request
from html import escape

import folium
import streamlit as st
from pyproj import Geod

_GEOD = Geod(ellps="WGS84")
_URL = "https://raw.githubusercontent.com/datasets/airport-codes/main/data/airport-codes.csv"

@st.cache_data(ttl=86400, max_entries=2, show_spinner=False)
def _all_airports():
    req = urllib.request.Request(_URL, headers={"User-Agent": "COVERAGEDIAGRAMS/2.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        # Guard against an accidental enormous remote payload.
        body = response.read(20_000_001)
    if len(body) > 20_000_000:
        raise ValueError("Airport dataset is larger than allowed download")
    rows = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    output = []
    for row in rows:
        if row.get("type") not in ("large_airport", "medium_airport", "small_airport", "heliport"):
            continue
        try:
            coordinate = str(row.get("coordinates") or "").split(",")
            lat, lon = float(coordinate[0]), float(coordinate[1])
        except (ValueError, IndexError):
            continue
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            continue
        output.append({"lat": lat, "lon": lon,
                       "icao": row.get("icao_code") or row.get("ident", ""),
                       "name": row.get("name", ""), "type": row.get("type", ""),
                       "elevation_ft": row.get("elevation_ft", "")})
    return output

def nearby(lat, lon, radius_km=120, types=None):
    if types is None:
        types = ["large_airport", "medium_airport", "small_airport", "heliport"]
    if not types:
        return []
    selected = []
    for point in _all_airports():
        if point["type"] not in types or abs(point["lat"]-lat) > radius_km/110:
            continue
        _, _, d = _GEOD.inv(lon, lat, point["lon"], point["lat"])
        if d <= radius_km*1000:
            selected.append({**point, "distance_km": round(d/1000, 1)})
    return sorted(selected, key=lambda x:x["distance_km"])[:350]

def add_airports(map_obj, airports):
    group = folium.FeatureGroup(name="Airports / letiště", show=True, overlay=True)
    for a in airports:
        tip = escape(a["name"]) + " · " + escape(a["icao"])
        folium.CircleMarker([a["lat"], a["lon"]], radius=5,
                            color="#87b7ff", fill=True, fill_color="#87b7ff",
                            fill_opacity=.95, weight=1, tooltip=tip,
                            popup=folium.Popup(tip + "<br>Airport elevation: " +
                                               escape(str(a["elevation_ft"])) + " ft AMSL", max_width=300)).add_to(group)
    group.add_to(map_obj)

def controls(lat, lon, prefix):
    show = st.checkbox("Letiště a heliporty · OurAirports", False, key=prefix+"_show")
    if not show:
        return []
    radius = st.slider("Dosah letišť [km]", 20, 300, 120, 10, key=prefix+"_radius")
    kind = st.multiselect("Kategorie letišť",
                          ["large_airport", "medium_airport", "small_airport", "heliport"],
                          default=["large_airport", "medium_airport", "small_airport"],
                          key=prefix+"_types")
    try:
        airports = nearby(lat, lon, radius, kind)
        st.caption(f"Letiště: {len(airports)} · OurAirports / airport-codes (informativní vrstva).")
        return airports
    except Exception as exc:
        st.warning("Databáze letišť není dostupná: " + str(exc)[:130])
        return []

def geojson_bytes(airports):
    return json.dumps({"type":"FeatureCollection","features":[
        {"type":"Feature","properties":{k:v for k,v in a.items() if k not in ("lat","lon")},
         "geometry":{"type":"Point","coordinates":[a["lon"],a["lat"]]}}
        for a in airports]}, ensure_ascii=False, indent=2).encode("utf-8")

def csv_bytes(airports):
    output = io.StringIO()
    columns = ["icao","name","type","lat","lon","elevation_ft","distance_km"]
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(airports)
    return output.getvalue().encode("utf-8-sig")

def kml_bytes(airports):
    from xml.etree import ElementTree as ET
    ns = "http://www.opengis.net/kml/2.2"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}kml")
    doc = ET.SubElement(root, f"{{{ns}}}Document")
    ET.SubElement(doc, f"{{{ns}}}name").text = "COVERAGEDIAGRAMS / airports"
    for airport in airports:
        pm = ET.SubElement(doc, f"{{{ns}}}Placemark")
        ET.SubElement(pm, f"{{{ns}}}name").text = airport["name"]
        ET.SubElement(pm, f"{{{ns}}}description").text = (
            f'{airport["icao"]} · {airport["type"]} · elev {airport["elevation_ft"]} ft AMSL')
        point = ET.SubElement(pm, f"{{{ns}}}Point")
        ET.SubElement(point, f"{{{ns}}}coordinates").text = (
            f'{airport["lon"]:.7f},{airport["lat"]:.7f},0')
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
