"""Live OpenSky traffic over a computed radar coverage layer."""
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import folium
import numpy as np
import streamlit as st
from folium.plugins import Fullscreen
from pyproj import Geod
from streamlit_folium import st_folium

from web_support import coverage_geojson
import radar_core as core

GEOD = Geod(ellps="WGS84")
NM_M = 1852.0
MAX_NM = 260

@st.cache_data(ttl=15, show_spinner=False)
def _traffic(lat, lon, provider):
    """Return normalized aircraft positions; API radius is limited to 250 NM."""
    hosts = {"ADSB.lol": "https://api.adsb.lol",
             "Airplanes.live": "https://api.airplanes.live"}
    url = f"{hosts[provider]}/v2/point/{lat:.5f}/{lon:.5f}/250"
    req = urllib.request.Request(url, headers={"User-Agent": "COVERAGEDIAGRAMS/1.0",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=18) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{provider}: HTTP {exc.code} ({exc.reason})") from exc
    raw = payload.get("ac", [])
    rows = []
    for ac in raw:
        if ac.get("lat") is None or ac.get("lon") is None:
            continue
        altitude_ft = ac.get("alt_geom")
        if not isinstance(altitude_ft, (int, float)):
            altitude_ft = ac.get("alt_baro")
        altitude_m = float(altitude_ft) * 0.3048 if isinstance(altitude_ft, (int, float)) else None
        row = [None] * 14
        row[0] = ac.get("hex", "")
        row[1] = ac.get("flight", "")
        row[5] = ac["lon"]
        row[6] = ac["lat"]
        row[7] = altitude_m
        row[13] = altitude_m
        rows.append(row)
    now = payload.get("now")
    if isinstance(now, (int, float)) and now > 1e11:
        now /= 1000
    return now, rows

def _sample(result, lat, lon):
    c = result["config"]
    bearing, _, distance_m = GEOD.inv(c.lon, c.lat, lon, lat)
    az = np.asarray(result["az"])
    ranges = np.asarray(result["distance"])
    if distance_m > ranges[-1] or distance_m < 0:
        return None
    idx = int(np.argmin(np.abs((az - bearing + 180) % 360 - 180)))
    k = int(np.argmin(np.abs(ranges-distance_m)))
    if not bool(result["known"][idx, k]):
        return None
    return float(result["lower"][idx, k]), float(result["upper"][idx, k])

def _render(result, level_ft, traffic):
    c = result["config"]
    m = folium.Map(location=[c.lat,c.lon], zoom_start=7, tiles="OpenStreetMap",
                   control_scale=True, prefer_canvas=True)
    geo = coverage_geojson(result, level_ft)
    if geo.get("features"):
        folium.GeoJson(geo, name=f"Pokrytí FL {level_ft/100:g}",
                       style_function=lambda _: {"color":"#20bfb2","weight":1,
                                                 "fillColor":"#20bfb2","fillOpacity":0.25}).add_to(m)
    for nm in range(20, MAX_NM+1, 20):
        folium.Circle([c.lat,c.lon], radius=nm*NM_M, color="#7f9bb8",
                      weight=1, opacity=0.65, fill=False,
                      tooltip=f"{nm} NM").add_to(m)
    folium.Marker([c.lat,c.lon], tooltip="RADAR",
                  icon=folium.Icon(color="orange", icon="signal")).add_to(m)
    counts = {"visible":0,"hidden":0,"unknown":0}
    for row in traffic:
        if len(row)<14 or row[5] is None or row[6] is None:
            continue
        lon,lat = float(row[5]),float(row[6])
        az,_,dist = GEOD.inv(c.lon,c.lat,lon,lat)
        if dist > MAX_NM*NM_M:
            continue
        altitude = row[13] if row[13] is not None else row[7]
        sampled = _sample(result,lat,lon)
        if altitude is None or sampled is None:
            status="unknown"
        elif sampled[0] <= float(altitude) <= sampled[1]:
            status="visible"
        else:
            status="hidden"
        counts[status]+=1
        color={"visible":"#21e3a2","hidden":"#fa6874","unknown":"#f6c85f"}[status]
        callsign=(row[1] or row[0] or "UNKNOWN").strip()
        alt_text=f"{float(altitude)/0.3048:.0f} ft AMSL" if altitude is not None else "N/A"
        label={"visible":"POTENCIÁLNĚ VIDITELNÝ","hidden":"MIMO VYPOČTENÉ KRYTÍ",
               "unknown":"NEURČENO"}[status]
        popup=(f"<b>{callsign}</b><br>{label}<br>Výška: {alt_text}"
               f"<br>Vzdálenost: {dist/NM_M:.1f} NM<br>Azimut: {az%360:.1f}°")
        folium.CircleMarker([lat,lon], radius=4, color=color, weight=1,
                            fill=True,fill_color=color,fill_opacity=0.95,
                            tooltip=f"{callsign} · {label}",
                            popup=folium.Popup(popup,max_width=240)).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    Fullscreen().add_to(m)
    return m,counts

@st.fragment(run_every="15s")
def _live_frame(result, level_ft, provider):
    try:
        timestamp, states = _traffic(round(result["config"].lat,5),round(result["config"].lon,5),provider)
    except Exception as exc:
        st.warning("ADS-B zdroj momentálně nevrací data. Zkus přepnout poskytovatele.")
        st.caption(f"{type(exc).__name__}: {str(exc)[:180]}")
        return
    m,counts=_render(result,level_ft,states)
    when=datetime.fromtimestamp(timestamp,timezone.utc).strftime("%H:%M:%S UTC") if timestamp else "N/A"
    st.caption(f"{provider} snapshot: {when} · aktualizace cca 15 s · "
               f"🟢 {counts['visible']} potenciálně viditelných · "
               f"🔴 {counts['hidden']} mimo krytí · 🟡 {counts['unknown']} neurčeno")
    st_folium(m,height=680,use_container_width=True,key=f"simulation_{level_ft}",returned_objects=[])
    st.caption("Simulace, nikoli skutečné radarové detekce. Posouzení využívá výšku letadla "
               "a vypočtenou spodní/horní hranici pokrytí; nezahrnuje RCS, výkon, "
               "maskování provozem ani omezení ADS-B zdroje. Kružnice 20–260 NM, "
               "krytí jen do vypočteného dosahu radaru.")

@st.dialog("LIVE TRAFFIC / Simulace radarového pokrytí",width="large")
def simulation_dialog(result,level_ft,provider):
    st.markdown(f"**Vrstva: {core.level_label(level_ft)}** · radar: "
                f"{result['config'].lat:.4f}°, {result['config'].lon:.4f}°")
    _live_frame(result,level_ft,provider)

def simulation_tab(result,levels):
    st.subheader("LIVE SIMULATION / ADS-B")
    st.caption("Živé ADS-B polohy letadel nad vypočteným radarovým pokrytím. "
               "Kružnice po 20 NM až do 260 NM.")
    if result is None:
        st.info("Nejprve spusť výpočet v NASTAVENÍ.")
        return
    options=list(levels)
    if not options:
        st.info("Nejprve vyber letové hladiny v NASTAVENÍ.")
        return
    selected=st.selectbox("Letová hladina pro vrstvu pokrytí",options,
                          format_func=core.level_label,key="simulation_level")
    st.caption("Barva letadla se vyhodnocuje podle jeho aktuální hlášené výšky, "
               "nikoliv podle zvolené hladiny. Zvolená hladina určuje mapový podklad.")
    provider = st.selectbox("Zdroj živých ADS-B dat", ["ADSB.lol", "Airplanes.live"],
                            key="simulation_provider")
    st.caption("Veřejná API poskytují maximálně 250 NM kolem radaru; kružnice 260 NM "
               "zůstává orientační. Data nejsou radarové ploty.")
    if st.button("▶ OTEVŘÍT LIVE SIMULACI",type="primary",key="open_simulation"):
        simulation_dialog(result,selected,provider)
