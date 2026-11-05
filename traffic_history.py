"""Analyze imported historical ADS-B observations against computed geometric coverage."""
import io
import pandas as pd
import folium
import streamlit as st

from live_simulation import _sample

def render_history(result):
    with st.expander("HISTORICAL TRAFFIC / Historické lety (CSV import)", expanded=False):
        st.caption("Importuj vlastní pozorování ve sloupcích: timestamp, icao24, lat, lon, altitude_m "
                   "(případně altitude_ft). Zdrojem mohou být povolené exporty ADS-B. "
                   "Tato funkce žádné historické záznamy automaticky nestahuje.")
        uploaded = st.file_uploader("Historická ADS-B data · CSV", type=["csv"], key="historical_csv")
        if uploaded is None:
            return
        if uploaded.size > 15_000_000:
            st.error("Soubor je příliš velký (max. 15 MB).")
            return
        try:
            data = pd.read_csv(io.BytesIO(uploaded.getvalue()), nrows=25001)
            if len(data) > 25000:
                st.warning("Zpracováno pouze prvních 25 000 záznamů.")
                data = data.iloc[:25000].copy()
            required = {"lat", "lon"}
            if not required.issubset(data.columns):
                st.error("CSV musí obsahovat sloupce lat, lon.")
                return
            if "altitude_m" not in data.columns:
                if "altitude_ft" in data.columns:
                    data["altitude_m"] = pd.to_numeric(data["altitude_ft"], errors="coerce") * .3048
                else:
                    st.error("CSV musí obsahovat altitude_m nebo altitude_ft.")
                    return
            for col in ("lat", "lon", "altitude_m"):
                data[col] = pd.to_numeric(data[col], errors="coerce")
            data = data.dropna(subset=["lat", "lon", "altitude_m"])
            data = data[data["lat"].between(-90, 90) & data["lon"].between(-180, 180)]
            a, b = st.columns(2)
            with a:
                alt_range = st.slider("Výškové pásmo [m AMSL]", -500, 16000,
                                      (-500, 16000), 100, key="history_alt_filter")
            with b:
                if "icao24" in data.columns:
                    needle = st.text_input("ICAO24 obsahuje", "", key="history_icao_filter").strip().lower()
                    if needle:
                        data = data[data["icao24"].astype(str).str.lower().str.contains(needle, regex=False)]
                else:
                    st.caption("Pro filtrování jednotlivých letadel přidej sloupec icao24.")
            data = data[data["altitude_m"].between(*alt_range)].copy()
            statuses = []
            for row in data.itertuples():
                bounds = _sample(result, row.lat, row.lon)
                statuses.append("Unknown / outside DEM" if bounds is None else (
                    "Inside geometric coverage" if bounds[0] <= row.altitude_m <= bounds[1]
                    else "Outside geometric coverage"))
            data["coverage_status"] = statuses
            counts = data["coverage_status"].value_counts()
            st.markdown("**Výsledky porovnání pozorovaných poloh s geometrickým krytím**")
            c1, c2, c3 = st.columns(3)
            c1.metric("Uvnitř", int(counts.get("Inside geometric coverage", 0)))
            c2.metric("Mimo", int(counts.get("Outside geometric coverage", 0)))
            c3.metric("Neurčeno", int(counts.get("Unknown / outside DEM", 0)))
            st.bar_chart(counts)
            if not data.empty:
                view = folium.Map(location=[result["config"].lat, result["config"].lon],
                                  zoom_start=7, tiles="OpenStreetMap", control_scale=True)
                colors = {"Inside geometric coverage": "#43d4a3",
                          "Outside geometric coverage": "#fb7979",
                          "Unknown / outside DEM": "#f4ce6c"}
                # Stratified limit keeps the map responsive, statistics use every filtered row.
                sample = data.groupby("coverage_status", group_keys=False).head(500)
                for record in sample.itertuples():
                    color = colors[record.coverage_status]
                    folium.CircleMarker(
                        [record.lat, record.lon], radius=2.5, color=color, fill=True,
                        fill_color=color, fill_opacity=.8, weight=0,
                        tooltip=f"{record.coverage_status} · {record.altitude_m:.0f} m AMSL"
                    ).add_to(view)
                from branca.element import Element
                view.get_root().html.add_child(Element(
                    '<div style="position:absolute;z-index:9999;bottom:25px;left:10px;'
                    'background:#09283c;color:#fff;padding:10px;border-radius:8px;'
                    'font:12px system-ui">🟢 In coverage<br>🔴 Outside<br>🟡 Unknown'
                    '<br>ADS-B observations / geometrical estimate</div>'))
                from streamlit_folium import st_folium
                st_folium(view, height=470, use_container_width=True, key="historical_traffic_map",
                          returned_objects=[])
                st.caption(f"Mapa obsahuje nejvýše 500 pozorování na kategorii (celkem {len(sample)}); "
                           "statistiky a export používají všechna vyfiltrovaná pozorování.")
            st.dataframe(data.head(2000), use_container_width=True, height=310)
            st.download_button("Export vyhodnocení · CSV",
                               data.to_csv(index=False).encode("utf-8-sig"),
                               file_name="traffic_coverage_analysis.csv", mime="text/csv",
                               key="history_csv_download")
            st.caption("Vyhodnocení jednotlivých ADS-B pozic, nikoliv skutečné detekční pravděpodobnosti "
                       "nebo procentuálního pokrytí všech letadel. Opakované polohy jednoho letadla "
                       "se počítají jako samostatná pozorování.")
        except Exception as exc:
            st.error(f"CSV nelze analyzovat: {exc}")
