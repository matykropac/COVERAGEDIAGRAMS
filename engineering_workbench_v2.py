"""Streamlit tools for the experimental v2 sensor and 3D antenna workbench."""
from dataclasses import asdict
import numpy as np
import plotly.graph_objects as go
import streamlit as st

from engineering_contracts import SensorDefinition, SensorType
from sensor_registry import add_sensor, list_sensors
from antenna_pattern_3d import read_3d_csv, half_power_beamwidth


def render_sensor_registry(site=None):
    st.caption("Sensor Registry · nezávislá evidence více senzorů. Bez přepsání aktivního PSR/SSR/PAR výpočtu.")
    registry=st.session_state.setdefault("v2_sensor_registry",{})
    if registry:
        st.dataframe([{
            "ID":item.sensor_id,"TYP":item.kind.value,"LAT":item.latitude_deg,
            "LON":item.longitude_deg,"VÝŠKA AMSL [m]":item.site_altitude_m_amsl,
            "ANTÉNA AGL [m]":item.antenna_height_m_agl,
            "AZ TRUE [°]":item.orientation_deg_true,"REV":item.revision,
        } for item in list_sensors(registry)],hide_index=True,use_container_width=True)
    else:
        st.info("V tomto pracovním sezení nejsou registrované žádné senzory.")
    default_lat=float(site[0]) if site is not None else 0.
    default_lon=float(site[1]) if site is not None else 0.
    with st.form("v2_sensor_create_form",clear_on_submit=False):
        name=st.text_input("SENSOR ID",placeholder="SSR-LATI")
        kind=st.selectbox("Typ senzoru",options=[t.value for t in SensorType])
        c1,c2=st.columns(2)
        with c1:
            lat=st.number_input("Latitude · WGS84",min_value=-90.,max_value=90.,value=default_lat,format="%.6f")
            site_alt=st.number_input("Nadmořská výška stanoviště [m AMSL]",value=0.,format="%.2f")
            bearing=st.number_input("Orientace antény [° TRUE]",min_value=0.,max_value=359.99,value=0.,format="%.2f")
        with c2:
            lon=st.number_input("Longitude · WGS84",min_value=-180.,max_value=180.,value=default_lon,format="%.6f")
            agl=st.number_input("Výška středu antény [m AGL]",min_value=0.,max_value=5000.,value=20.,format="%.2f")
        submitted=st.form_submit_button("PŘIDAT SENZOR DO REGISTRU",type="primary",use_container_width=True)
    if submitted:
        try:
            sensor=SensorDefinition(name.strip(),SensorType(kind),lat,lon,site_alt,agl,bearing)
            st.session_state["v2_sensor_registry"]=add_sensor(registry,sensor)
            st.success("Senzor uložen do pracovního registru. Aktivní solver nebyl změněn.")
            st.rerun()
        except (ValueError,TypeError) as exc:
            st.error(str(exc))
    st.caption("Registr je zatím pouze v session. Trvalé uložení, načtení a sdílení mezi projekty bude součástí nové verze projektového formátu.")


def render_3d_pattern():
    st.caption("3D AZ/EL MATRIX · import CSV: az_deg,el_deg,gain_db · UTF-8 · max 200 MB / 1 000 000 vzorků.")
    st.code("az_deg,el_deg,gain_db\n0,-1,-25\n0,0,-12\n0,1,0\n...",language="csv")
    upload=st.file_uploader("Vyber 3D anténní diagram",type=["csv"],key="v2_pattern_3d_file")
    origin=st.selectbox("Původ dat",["UNKNOWN","MEASURED","SIMULATED","DERIVED"],
        key="v2_pattern_3d_origin",help="MEASURED nastav pouze u doložených měřených dat. Pro neznámá data ponech UNKNOWN.")
    if st.button("NAČÍST A OVĚŘIT 3D MŘÍŽKU",disabled=upload is None,
                 key="v2_import_3d",use_container_width=True):
        from busy_overlay import busy_overlay
        try:
            with busy_overlay("ANTENNA LAB · 3D IMPORT","Kontroluji AZ/EL mřížku, jednotky a integritu souboru…"):
                blob=upload.getvalue()
                pattern=read_3d_csv(blob,source_name=upload.name,origin=origin)
                st.session_state["v2_pattern_3d"]=pattern
            st.success("Mřížka načtena a ověřena; výpočetní model radaru zůstává beze změny.")
        except (ValueError,TypeError,UnicodeError,MemoryError) as exc:
            st.error("Import selhal: "+str(exc))
    pattern=st.session_state.get("v2_pattern_3d")
    if pattern is None:return
    st.caption(f"ZDROJ: {pattern.source_name} · {pattern.origin} · SHA-256: {pattern.source_sha256}")
    a,b,c=st.columns(3)
    a.metric("AZ vzorky",len(pattern.az_deg))
    b.metric("EL vzorky",len(pattern.el_deg))
    c.metric("Max. zisk",f"{pattern.peak_db:.2f} dB")
    # Present sampled visualization; the complete original matrix remains in memory.
    si=max(1,int(np.ceil(len(pattern.az_deg)/240)))
    sj=max(1,int(np.ceil(len(pattern.el_deg)/220)))
    fig=go.Figure(data=go.Heatmap(
        x=pattern.az_deg[::si],y=pattern.el_deg[::sj],
        z=pattern.gain_db[::si,::sj].T,colorscale="Viridis",colorbar_title="dB"))
    fig.update_layout(height=350,margin=dict(t=15,b=30,l=15,r=12),
                      xaxis_title="AZ [°]",yaxis_title="EL [°]",template="plotly_white")
    st.plotly_chart(fig,use_container_width=True,key="v2_pattern_3d_chart")
    cut=st.selectbox("Elevační řez [°]",options=pattern.el_deg.tolist(),
                     index=int(np.argmin(abs(pattern.el_deg))),key="v2_3d_cut")
    axis,gain,selected=pattern.az_cut(cut)
    st.line_chart({"AZ [°]":axis,"Zisk [dB]":gain},x="AZ [°]",y="Zisk [dB]",height=220)
    try:
        hpbw=half_power_beamwidth(axis,gain)
        st.metric("AZ HPBW · −3 dB",f"{hpbw:.3f}°" if hpbw is not None else "N/A")
    except ValueError:
        st.caption("HPBW nelze pro tento řez spolehlivě určit.")
    st.info("3D data jsou zatím určená k analýze a porovnání. Aplikovat je do fyzikálního solveru půjde až po ověření vazby na RF kanály a link budget.")
