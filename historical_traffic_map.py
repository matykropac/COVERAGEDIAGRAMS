"""Historical ADS-B flight paths from adsb.aero's public read-only API.

API guide: https://adsb.aero/llms.txt
Query is user-triggered and bounded by time, radius and maximum returned flights.
"""
import json
from datetime import datetime, time, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import folium
import streamlit as st
from streamlit_folium import st_folium
from traffic_overlay import traffic_csv
from aviation_basemap import configured_key, add_to_map

API = "https://adsb.aero/api/v1"


def query_historical(lat, lon, date, start_hour, duration_hours, radius_km, limit):
    beginning = datetime.combine(date, time(hour=int(start_hour)), tzinfo=timezone.utc)
    ending = beginning + timedelta(hours=int(duration_hours))
    query = {
        "match": {"trajectory_intersects": {
            "geometry": {"type": "Circle",
                         "coordinates": [float(lon), float(lat)],
                         "radius": int(radius_km) * 1000},
            "time_from": beginning.isoformat().replace("+00:00", "Z"),
            "time_to": ending.isoformat().replace("+00:00", "Z"),
        }},
        "end_date": (ending + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "window_days": 2,
        "limit": int(limit),
        "include_path": True,
    }
    req = Request(
        API + "/query", data=json.dumps(query).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": "COVERAGEDIAGRAMS/1.0 historical traffic"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as response:
            data = json.load(response)
    except HTTPError as exc:
        message = exc.read(300).decode("utf-8", errors="replace")
        raise RuntimeError(f"Server vrátil HTTP {exc.code}: {message}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Historická data nejsou dostupná: {type(exc).__name__}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("flights"), list):
        raise ValueError("Historický server vrátil neočekávaná data.")
    # The API uses flight start time for pagination. Enforce the actual
    # requested interval locally on each returned timestamp.
    return data["flights"], data.get("cursor"), beginning.timestamp(), ending.timestamp()


def flight_segments(flight, lower_ts, upper_ts):
    path = flight.get("path") or {}
    if path.get("type") != "MultiLineString":
        return []
    parts = path.get("coordinates", [])
    timeparts = flight.get("timestamps") or []
    result = []
    for idx, segment in enumerate(parts):
        if not isinstance(segment, list):
            continue
        ts = timeparts[idx] if idx < len(timeparts) else []
        # Keep only observations in the selected UTC time interval.
        points = []
        for j, location in enumerate(segment):
            if not isinstance(location, (list, tuple)) or len(location) < 2:
                continue
            if j >= len(ts):
                continue
            try:
                timestamp = float(ts[j])
                if not lower_ts <= timestamp < upper_ts:
                    if len(points) > 1:
                        result.append(points)
                    points = []
                    continue
                lon, lat = float(location[0]), float(location[1])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    points.append((lat, lon, location[2] if len(location) > 2 else None, timestamp))
            except (TypeError, ValueError):
                continue
        if len(points) > 1:
            result.append(points)
    return result


def render_historical_map(result):
    st.markdown("**HISTORICKÁ MAPA · ADS-B TRAJEKTORIE**")
    st.caption("Vyhledávání již zaznamenaných letů přes adsb.aero (bez API klíče). "
               "Časy jsou UTC. Zdroj používá archiv adsb.lol.")
    c = result["config"]
    controls = st.columns([1.4, 1, 1, 1, 1], gap="small")
    with controls[0]:
        picked_date = st.date_input("Datum (UTC)", value=datetime.now(timezone.utc).date()-timedelta(days=2),
                                    max_value=datetime.now(timezone.utc).date(), key="historic_map_date")
    with controls[1]:
        start_hour = st.selectbox("Od (UTC)", list(range(0, 24)), index=8,
                                  format_func=lambda v: f"{v:02d}:00", key="historic_map_hour")
    with controls[2]:
        duration = st.selectbox("Délka", [1, 2, 3, 6, 12, 24], index=2,
                                format_func=lambda v: f"{v} h", key="historic_map_duration")
    with controls[3]:
        radius = st.selectbox("Okolí radaru", [20, 40, 75, 100],
                              index=1, format_func=lambda v: f"{v} km",
                              key="historic_map_radius")
    with controls[4]:
        limit = st.selectbox("Max. letů", [25, 50, 100, 200],
                             index=1, key="historic_map_limit")
    if st.button("NAČÍST HISTORICKÉ TRASY", type="primary", key="historic_map_load"):
        if datetime.combine(picked_date, time(hour=start_hour), tzinfo=timezone.utc) >= datetime.now(timezone.utc):
            st.warning("Vyber již uplynulý interval UTC.")
        else:
            try:
                with st.spinner("Hledám zaznamenané trajektorie…"):
                    flights, cursor, t0, t1 = query_historical(
                        c.lat, c.lon, picked_date, start_hour, duration, radius, limit)
                st.session_state["historic_map_result"] = (
                    (round(c.lat, 5), round(c.lon, 5), picked_date,
                     start_hour, duration, radius, limit),
                    flights, cursor, t0, t1)
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))

    signature = (round(c.lat, 5), round(c.lon, 5), picked_date,
                 start_hour, duration, radius, limit)
    saved = st.session_state.get("historic_map_result")
    if saved is None or saved[0] != signature:
        st.info("Vyber období a klikni na NAČÍST HISTORICKÉ TRASY.")
        return
    _, flights, cursor, t0, t1 = saved
    view = folium.Map(location=[c.lat, c.lon], zoom_start=8,
                      tiles="OpenStreetMap", control_scale=True, prefer_canvas=True)
    add_to_map(view, configured_key())
    folium.Circle([c.lat, c.lon], radius=radius*1000,
                  color="#70a4ce", weight=1, fill=False,
                  tooltip=f"Oblast dotazu {radius} km").add_to(view)
    folium.Marker([c.lat, c.lon], tooltip="Radar",
                  icon=folium.Icon(color="orange", icon="signal")).add_to(view)
    rendered = 0
    csv_records = []
    for flight in flights:
        segments = flight_segments(flight, t0, t1)
        callsign = str(flight.get("callsign") or flight.get("icao24") or "Unknown").strip()
        for segment in segments:
            rendered += 1
            folium.PolyLine([(p[0], p[1]) for p in segment], color="#15b9e7",
                            weight=2.5, opacity=.7, tooltip=callsign).add_to(view)
            # Preserve time and altitude for downstream CSV analysis.
            for lat, lon, altitude_ft, timestamp in segment:
                try:
                    altitude_ft = float(altitude_ft) if altitude_ft is not None else None
                except (ValueError, TypeError):
                    altitude_ft = None
                csv_records.append({
                    "timestamp_utc": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                    "icao24": flight.get("icao24") or "",
                    "callsign": callsign, "lat": lat, "lon": lon,
                    "altitude_ft": altitude_ft,
                    "altitude_m": round(altitude_ft*.3048, 1) if altitude_ft is not None else None,
                    "source": "adsb.aero / adsb.lol archive",
                })
    a, b, d = st.columns(3)
    a.metric("Vrácené lety", len(flights))
    b.metric("Zobrazené úseky", rendered)
    d.metric("Záznamy v CSV", len(csv_records))
    if cursor:
        st.caption("Zobrazen pouze první výsledek dotazu; další lety mohou být dostupné. "
                   "Pro menší výběr zúž čas nebo oblast.")
    folium.LayerControl(collapsed=True).add_to(view)
    st_folium(view, height=520, use_container_width=True,
              key="historical_flights_map", returned_objects=[])
    if csv_records:
        st.download_button("STÁHNOUT ZAZNAMENANÉ POZICE · CSV",
                           data=traffic_csv(csv_records),
                           file_name=f"historical_traffic_{picked_date}.csv",
                           mime="text/csv", key="historical_flights_csv")
    st.caption("Zobrazeny jsou skutečně archivované ADS-B polohy, nikoli všechny skutečně "
               "proletěné lety. Nepřítomnost trajektorie není důkazem absence provozu. "
               "Zdroj: adsb.aero / adsb.lol; respektuj licenci původních dat.")
