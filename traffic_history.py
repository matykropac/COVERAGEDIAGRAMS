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
            st.dataframe(data.head(2000), use_container_width=True, height=310)
            st.download_button("Export vyhodnocení · CSV",
                               data.to_csv(index=False).encode("utf-8-sig"),
                               file_name="traffic_coverage_analysis.csv", mime="text/csv",
                               key="history_csv_download")
            st.caption("Vyhodnocení jednotlivých ADS-B pozic, nikoliv skutečné detekční pravděpodobnosti "
                       "nebo procentuálního pokrytí všech letadel. Opakované polohy jednoho letadla "
                       "se počítají jako samostatná pozorování.")
        except (ValueError, UnicodeError, TypeError, KeyError) as exc:
            st.error(f"CSV nelze analyzovat: {exc}")
