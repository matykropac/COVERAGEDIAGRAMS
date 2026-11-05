"""Map-first COVERAGEDIAGRAMS cockpit.

The geographical map is always the workspace; tools open in Streamlit dialogs.
Legacy mode remains available until feature parity is verified.
"""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import hashlib

import folium
import streamlit as st
import numpy as np
from folium.plugins import Fullscreen, MeasureControl
from streamlit_folium import st_folium
from matplotlib.colors import to_hex

import radar_core as core
import environment_layers as env
from aviation_basemap import add_to_map as add_openaip_map
from web_support import coverage_geojson
from obstacles import apply_obstacles, obstacle_polygon, obstacle_signature
from obstacle_ui import render_obstacle_editor
from live_simulation import simulation_tab
from project_file import save_project, load_project
from ssr_custom import load_measured_ssr
from wind_turbines import load_wind_turbines, add_wind_layer
from selected_export import FORMATS, build_selected_zip

STYLES = """
<style>
/* Scoped map-first workspace; no fixed tab-list positioning or hacks. */
.cd-topline{display:flex;justify-content:space-between;align-items:center;
  gap:18px;background:#ffffff;color:#172b40;border:1px solid #dee5ed;
  border-radius:9px;padding:12px 18px;margin:0 0 8px;font-family:system-ui}
.cd-wordmark{font-size:17px;font-weight:760;letter-spacing:.025em;color:#172b40}
.cd-wordmark small{display:block;color:#708397;font-size:9px;letter-spacing:.17em;margin-bottom:3px}
.cd-meta{color:#75879a;font-size:11px}
.cd-map-label{font-weight:680;color:#263d55;font-size:12px;letter-spacing:.04em}
.cd-workspace-foot{color:#718398;font-size:11px;margin-top:7px}
[data-testid="stAppViewContainer"]{background:#f3f6fa!important;color:#253b52!important}
[data-testid="stMainBlockContainer"],.block-container{max-width:100%!important;padding:12px 20px 22px!important}
[data-testid="stVerticalBlock"]{gap:.5rem!important}
[data-testid="stHorizontalBlock"]{gap:.55rem!important}
[data-testid="stColumn"] > div > [data-testid="stVerticalBlock"],
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]{
  background:transparent!important;border:0!important;padding:0!important;box-shadow:none!important}
[data-testid="stTabs"] [role="tab"]{min-width:0!important;padding:8px 14px!important}
[data-testid="stButton"]>button{
  border-radius:6px!important;min-height:38px!important;
  background:#fff!important;color:#283f55!important;border:1px solid #d5e0eb!important;
  box-shadow:0 1px 3px rgba(22,43,65,.06)!important;font-size:12px!important}
[data-testid="stButton"]>button[kind="primary"]{
  background:#2865d9!important;color:white!important;border-color:#2865d9!important}
[data-testid="stWidgetLabel"] p{font-size:12px!important;color:#50677d!important}
[data-testid="stCaptionContainer"]{font-size:11px!important;color:#657b8e!important}
[data-testid="stDialog"]{color:#253c52}
[data-testid="stDialog"] [data-testid="stVerticalBlock"]{gap:.55rem!important}
[data-testid="stExpander"]{border-color:#d8e2eb!important;background:#fff!important}
iframe[title*="streamlit_folium"]{border-radius:9px!important;border:1px solid #d0dce8!important}
@media(max-width:850px){[data-testid="stMainBlockContainer"],.block-container{padding:8px!important}.cd-meta{display:none}}
</style>
"""


def _cfg():
    """Use explicit workspace keys; never modify legacy input widgets on a rerun."""
    model = st.session_state.get("ws_radar", "RL-2000")
    psr = st.session_state.get("ws_psr_nm", 100)
    range_km = float(40 if model == "PAR-NG" else core.radar_preset(model, psr))
    return core.Config(
        lat=float(st.session_state.get("ws_lat", 50.034)),
        lon=float(st.session_state.get("ws_lon", 15.781)),
        antenna_agl=float(st.session_state.get("ws_agl", 20.0)),
        radar_mode=model,
        bearing_deg=float(st.session_state.get("ws_bearing", 0.0)),
        range_km=range_km,csc_range_km=range_km,
        step_m=float(st.session_state.get("ws_step", 500)),
        az_step=float(st.session_state.get("ws_azstep", 1.0)),
        k=float(st.session_state.get("ws_k", 4/3)),
        min_elev=float(st.session_state.get("ws_min", -1.0)),
        max_elev=float(st.session_state.get("ws_max", 45.0)),
        antenna_tilt_deg=float(st.session_state.get("ws_tilt", -1.0)),
        beam_mode=st.session_state.get("ws_beam", "COMBINED") if model == "RL-2000" else "COMBINED",
        target_m=float(st.session_state.get("ws_target", 1000.0)),
        reference=st.session_state.get("ws_reference", "AMSL"),
        csc_enabled=True,
    )


def _pattern(config):
    if config.radar_mode == "PAR-NG":
        return core.builtin_par_pattern()
    if config.radar_mode == "SSR":
        if st.session_state.get("ws_ssr_diagram", "Generic Gaussian") == "Measured SSR.txt":
            return load_measured_ssr()
        return core.generic_ssr_pattern()
    return core.rl2000_dual_beam_pattern()


def _config_state_from_project(config):
    values = {
        "ws_radar": config.radar_mode, "ws_lat":config.lat,"ws_lon":config.lon,
        "ws_agl":config.antenna_agl,"ws_bearing":config.bearing_deg,
        "ws_step":int(config.step_m),"ws_azstep":float(config.az_step),
        "ws_k":config.k,"ws_min":config.min_elev,"ws_max":config.max_elev,
        "ws_tilt":config.antenna_tilt_deg,"ws_beam":config.beam_mode,
        "ws_target":config.target_m,"ws_reference":config.reference,
    }
    if config.radar_mode == "RL-2000":
        values["ws_psr_nm"] = min(core.PSR_RANGES_NM,key=lambda n:abs(core.radar_preset("RL-2000",n)-config.range_km))
    st.session_state.update(values)


@st.dialog("RADAR / Nastavení a výpočet", width="large")
def radar_dialog():
    st.caption("Nastav stanoviště, parametry a letové hladiny. Výsledek se objeví přímo v mapě.")
    site, settings = st.columns(2, gap="medium")
    with site:
        st.selectbox("Radar",["RL-2000","PAR-NG","SSR"],key="ws_radar")
        st.number_input("Latitude · WGS84",min_value=-80.0,max_value=80.0,value=50.034,
                        format="%.6f",key="ws_lat")
        st.number_input("Longitude · WGS84",min_value=-180.0,max_value=180.0,value=15.781,
                        format="%.6f",key="ws_lon")
        st.number_input("Výška antény [m AGL]",min_value=.1,max_value=5000.0,
                        value=20.0,key="ws_agl")
        radar=st.session_state["ws_radar"]
        if radar=="RL-2000":
            st.selectbox("Dosah PSR [NM]",list(core.PSR_RANGES_NM),
                         index=2,key="ws_psr_nm")
        if radar=="PAR-NG":
            st.number_input("Azimut osy [°]",0.,359.99,0.,key="ws_bearing")
        if radar=="SSR":
            st.selectbox("SSR anténa",["Generic Gaussian","Measured SSR.txt"],key="ws_ssr_diagram")
        st.selectbox("Zdroj terénu",["OpenTopography","DEM soubor"],key="ws_source")
        if st.session_state["ws_source"]=="DEM soubor":
            st.file_uploader("GeoTIFF / DTED / HGT",
                             type=["tif","tiff","dt0","dt1","dt2","hgt"],key="ws_dem")
        else:
            st.selectbox("DEM dataset",list(core.DATASETS),key="ws_dataset")
    with settings:
        st.select_slider("Radiální krok [m]",options=[25,50,100,250,500,1000,2000],
                         value=500,key="ws_step")
        st.select_slider("Azimutální krok [°]",options=[.25,.5,1.,2.,2.5,5.],
                         value=1.,key="ws_azstep")
        st.number_input("k-factor",.5,3.,4/3,format="%.4f",key="ws_k")
        st.number_input("Min. elevace [°]",-5.,88.,-1.,key="ws_min")
        st.number_input("Max. elevace [°]",-4.,89.,45.,key="ws_max")
        st.number_input("Tilt antény [°]",-15.,15.,-1.,key="ws_tilt")
        if st.session_state["ws_radar"]=="RL-2000":
            st.selectbox("Svazek",["COMBINED","LOW","HIGH"],key="ws_beam")
        st.number_input("Výška cíle [m]",-500.,30000.,1000.,key="ws_target")
        st.selectbox("Reference cíle",["AMSL","AGL"],key="ws_reference")
        choices=core.flight_levels_for(st.session_state["ws_radar"])
        default=[x for x in (3000,10000) if x in choices]
        st.multiselect("Letové hladiny [ft AMSL]",choices,default=default,
                       format_func=core.level_label,key="ws_levels")
    if st.button("VYPOČÍTAT KRYTÍ",type="primary",use_container_width=True,key="ws_calculate"):
        try:
            c=_cfg()
            c.validate()
            az,distance=core.axes(c)
            if len(az)*len(distance)>250000:
                raise ValueError("Výpočet přesahuje 250 000 vzorků. Zvětši krok.")
            with st.spinner("Načítám terén a počítám krytí…"):
                source=st.session_state.get("ws_source","OpenTopography")
                if source=="DEM soubor":
                    uploaded=st.session_state.get("ws_dem")
                    if uploaded is None:
                        raise ValueError("Nahraj DEM soubor.")
                    with tempfile.TemporaryDirectory(prefix="cd_workspace_") as work:
                        path=Path(work)/("terrain"+Path(uploaded.name).suffix.lower())
                        content=uploaded.getvalue()
                        path.write_bytes(content)
                        terrain,ground=core.sample(path,c,lambda *args:None)
                        provenance="DEM upload · SHA256 "+hashlib.sha256(content).hexdigest()
                else:
                    import os
                    api_key=os.environ.get("OPENTOPOGRAPHY_API_KEY","")
                    if not api_key:
                        try: api_key=str(st.secrets.get("OPENTOPOGRAPHY_API_KEY",""))
                        except (FileNotFoundError,KeyError,OSError): pass
                    if not api_key:
                        raise ValueError("OpenTopography vyžaduje klíč v Secrets (OPENTOPOGRAPHY_API_KEY).")
                    dataset=st.session_state.get("ws_dataset","COP30")
                    path=core.download(c,api_key,dataset,lambda *args:None)
                    terrain,ground=core.sample(path,c,lambda *args:None)
                    provenance="OpenTopography · "+dataset
                result=core.solve(c,terrain,ground,_pattern(c))
                apply_obstacles(result,st.session_state.get("obstacles",[]))
                result["obstacles_signature"]=obstacle_signature(st.session_state.get("obstacles",[]))
                result.update(source=provenance,completed_at=datetime.now(timezone.utc).isoformat(),
                              duration_s=0.0)
                st.session_state.result=result
                st.session_state.geometry={}
                st.session_state["ws_map_revision"]=st.session_state.get("ws_map_revision",0)+1
                st.session_state["ws_result_notice"]="Krytí úspěšně vypočteno."
            st.rerun()
        except Exception as exc:
            st.error(f"Výpočet se nepodařil: {str(exc)[:360]}")


@st.dialog("PŘEKÁŽKY / Editor",width="large")
def obstacles_dialog():
    c=_cfg()
    st.caption("Nakresli polygon a nastav jeho výšku. Po úpravě překážek spusť nový výpočet.")
    render_obstacle_editor(c.lat,c.lon)


@st.dialog("PROVOZ / Live a historie",width="large")
def traffic_dialog():
    simulation_tab(st.session_state.get("result"),st.session_state.get("ws_levels",[3000,10000]))


@st.dialog("MAPA / Zobrazení vrstev",width="large")
def layers_dialog():
    result=st.session_state.get("result")
    if result is None:
        st.info("Nejdřív vypočítej krytí. Mapový podklad OpenAIP je aktivní už teď.")
        return
    modes=["Jedna hladina","Porovnání","Cíl"]
    st.radio("Zobrazení",modes,key="ws_display_mode",horizontal=True)
    opts=st.session_state.get("ws_levels",list(core.flight_levels_for(result["config"].radar_mode)))
    available=[int(x) for x in opts if x in core.flight_levels_for(result["config"].radar_mode)]
    if st.session_state.get("ws_display_mode","Jedna hladina")=="Jedna hladina":
        if available: st.selectbox("Letová hladina",available,key="ws_map_level",
                                    format_func=core.level_label)
    elif st.session_state["ws_display_mode"]=="Porovnání":
        st.multiselect("Hladiny",available,default=available[:3],
                       key="ws_comparison",format_func=core.level_label)
    st.slider("Průhlednost",0.,1.,.42,.05,key="ws_map_opacity")
    st.checkbox("Zobrazit větrné elektrárny",value=False,key="ws_show_wind")
    st.caption("OpenAIP a další podklady lze zapínat v nabídce vrstev přímo v mapě.")


@st.dialog("ANALÝZA / Radarový profil",width="large")
def analysis_dialog():
    result=st.session_state.get("result")
    if result is None:
        st.info("Nejdřív vypočítej krytí.")
        return
    from matplotlib.figure import Figure
    az=result["az"]
    idx=st.select_slider("Azimut [°]",options=list(range(len(az))),
                         format_func=lambda i:f"{az[i]%360:.2f}°",
                         key="ws_profile_index")
    fig=Figure(figsize=(11,5),facecolor=core.PLOT_BG)
    try:
        core.profile_plot(fig,result=result,index=idx,
                          levels_ft=st.session_state.get("ws_levels",[]))
        st.pyplot(fig,use_container_width=True)
    finally:
        fig.clear()


@st.dialog("DATA / EXPORT",width="large")
def exports_dialog():
    result=st.session_state.get("result")
    if result is None:
        st.info("Export je dostupný po výpočtu.")
        return
    opts=tuple(core.flight_levels_for(result["config"].radar_mode))
    st.caption("Vyber položky do jednoho ZIPu.")
    groups=st.columns(3)
    names={
      "project":"Projekt CDPROJ","html":"Interaktivní mapa HTML",
      "terrain":"Mapa terénu","antenna":"Anténní diagram",
      "fl_png":"PNG po hladinách","png_dark":"PNG Dark","png_light":"PNG Light",
      "quickreport":"QuickReport",
      "kml":"KML","gpkg":"GeoPackage","tiff":"GeoTIFF",
      "npz":"RAW NPZ","csv":"Profil CSV","json":"Metadata JSON",
    }
    for n,(key,label) in enumerate(names.items()):
        with groups[n%3]: st.checkbox(label,key="ws_zip_"+key,value=key=="fl_png")
    chosen=st.multiselect("Letové hladiny [ft AMSL]",opts,
                          default=[x for x in st.session_state.get("ws_levels",[]) if x in opts],
                          format_func=core.level_label,key="ws_zip_levels")
    selected={key:bool(st.session_state.get("ws_zip_"+key)) for key in names}
    if st.button("PŘIPRAVIT ZIP",type="primary",use_container_width=True,key="ws_export_build"):
        try:
            with st.spinner("Připravuji export…"):
                proj=None
                if selected["project"]:
                    proj=save_project(result,levels=st.session_state.get("ws_levels",[]),
                                      obstacles=st.session_state.get("obstacles",[]))
                html=st.session_state.get("ws_map_html")
                blob=build_selected_zip(
                    result, selected=selected, flight_levels=chosen,
                    index=st.session_state.get("ws_profile_index",0),
                    alpha=st.session_state.get("ws_map_opacity",.42),
                    level_alphas={x:st.session_state.get("ws_map_opacity",.42) for x in chosen},
                    environment_items=[],project_bytes=proj,map_html=html)
                st.session_state["ws_zip_ready"]=blob
        except Exception as exc:st.error(f"Export selhal: {exc}")
    if st.session_state.get("ws_zip_ready"):
        st.download_button("STÁHNOUT ZIP",st.session_state["ws_zip_ready"],
                           file_name="COVERAGEDIAGRAMS_export.zip",mime="application/zip",
                           use_container_width=True)


def _draw_map():
    result=st.session_state.get("result")
    c=result["config"] if result is not None else _cfg()
    m=folium.Map(location=[c.lat,c.lon],zoom_start=8 if result else 9,
                 tiles=None,control_scale=True,prefer_canvas=True)
    for name,provider in core.BASEMAP_PROVIDERS.items():
        folium.TileLayer(provider["url"],name=name,attr=provider["attribution"],
                         max_zoom=provider["max_zoom"],overlay=False,
                         show=name=="OpenStreetMap").add_to(m)
    add_openaip_map(m)
    active=[]
    if result is not None:
        mode=st.session_state.get("ws_display_mode","Jedna hladina")
        levels=[x for x in st.session_state.get("ws_levels",[3000,10000])
                if x in core.flight_levels_for(c.radar_mode)]
        if mode=="Cíl":active=[None]
        elif mode=="Porovnání":active=st.session_state.get("ws_comparison",levels[:3])
        elif levels:active=[st.session_state.get("ws_map_level",levels[0])]
        for level in active:
            if level is not None and level not in core.flight_levels_for(c.radar_mode):
                continue
            geo=coverage_geojson(result,level)
            if geo.get("features"):
                color="#247ad3" if level is None else to_hex(core.level_color(level))
                layer=folium.FeatureGroup(name="Krytí cíle" if level is None else core.level_label(level))
                folium.GeoJson(geo,style_function=lambda feature,color=color:
                               {"color":color,"weight":1.5,"fillColor":color,
                                "fillOpacity":st.session_state.get("ws_map_opacity",.42)}).add_to(layer)
                layer.add_to(m)
        for item in result.get("obstacles",[]):
            folium.Polygon(obstacle_polygon(item,c.lat,c.lon),
                           color="#eb6a43",weight=2,fill=True,fill_opacity=.3).add_to(m)
        if st.session_state.get("ws_show_wind",False):
            try:
                wind=load_wind_turbines(round(c.lat,6),round(c.lon,6))
                add_wind_layer(m,wind,cluster_points=False)
            except Exception:pass
    folium.Marker([c.lat,c.lon],tooltip=f"{c.radar_mode} · RADAR",
                  icon=folium.Icon(color="orange",icon="signal")).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    Fullscreen().add_to(m)
    MeasureControl(primary_length_unit="kilometers").add_to(m)
    st_folium(m,height=730,use_container_width=True,
              key=f"ws_map_{st.session_state.get('ws_map_revision',0)}",
              returned_objects=[])
    st.session_state["ws_map_html"]=m.get_root().render().encode("utf-8")


def render_workspace():
    st.markdown(STYLES,unsafe_allow_html=True)
    st.markdown(
       '<div class="cd-topline"><div class="cd-wordmark">'
       '<small>RADAR COVERAGE ENGINEERING</small>COVERAGEDIAGRAMS'
       '</div><div class="cd-meta">MAP WORKSPACE · WGS84 · OpenAIP</div></div>',
       unsafe_allow_html=True)
    toolbar=st.columns([1.1,1.2,1.1,1.1,1.1,1.1,1.1,1.2],gap="small")
    items=[
      ("📡 Radar",radar_dialog),("▧ Překážky",obstacles_dialog),
      ("◉ Vrstvy",layers_dialog),("✈ Provoz",traffic_dialog),
      ("⌁ Analýza",analysis_dialog),("⇩ Export",exports_dialog)]
    for n,(label,handler) in enumerate(items):
        with toolbar[n]:
            if st.button(label,key="ws_toolbar_"+str(n),use_container_width=True):
                handler()
    with toolbar[6]:
        if st.button("⤢ Znovu načíst",key="ws_refresh",use_container_width=True):
            st.session_state["ws_map_revision"]=st.session_state.get("ws_map_revision",0)+1
            st.rerun()
    with toolbar[7]:
        if st.button("↩ Klasické UI",key="ws_legacy",use_container_width=True):
            st.query_params["classic"]="1"
            st.rerun()
    result=st.session_state.get("result")
    if result is None:
        st.caption("Mapa je připravena. Klikni na RADAR, nastav parametry a spusť výpočet.")
    else:
        c=result["config"]
        st.caption(f"{c.radar_mode} · {c.lat:.6f}, {c.lon:.6f} · dosah {c.range_km:g} km · "
                   f"{len(st.session_state.get('obstacles',[]))} překážek")
    if st.session_state.pop("ws_result_notice",None):
        st.success("Krytí vypočteno. Výsledné vrstvy jsou přímo v mapě.")
    _draw_map()
    st.markdown('<div class="cd-workspace-foot">OpenAIP aeronautical chart · '
                'Geometrický výpočet radarového krytí · Nelze používat pro navigaci</div>',
                unsafe_allow_html=True)
