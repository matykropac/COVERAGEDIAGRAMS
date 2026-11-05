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
from folium.plugins import Fullscreen, MeasureControl, Draw
from streamlit_folium import st_folium
from matplotlib.colors import to_hex

import radar_core as core
import environment_layers as env
import aviation_layers as aviation
import canopy_layers as canopy
from aviation_basemap import add_to_map as add_openaip_map
from web_support import coverage_geojson
from obstacles import apply_obstacles, obstacle_polygon, obstacle_signature
from site_picker import coordinates_from_map_click
from traffic_overlay import fetch_snapshot, add_traffic_layer
from obstacle_ui import render_obstacle_editor
from live_simulation import simulation_tab
from project_file import save_project, load_project
from ssr_custom import load_measured_ssr
from wind_turbines import load_wind_turbines, add_wind_layer
from geodata_obstacle_catalog import catalog_from_data, synchronize
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

h1,h2,h3,h4{color:#233c55!important}
h3{border-bottom:1px solid #dce5ef!important}
div[data-baseweb="select"]>div,div[data-baseweb="input"]{
  background:#fff!important;border:1px solid #ccd9e6!important;color:#273c52!important;
  border-radius:6px!important;min-height:36px!important;box-shadow:none!important}
div[data-baseweb="input"] input{color:#273c52!important}
div[data-baseweb="tag"]{background:#dfeafb!important;color:#244d80!important}
div[data-baseweb="tag"] span{color:#244d80!important}
[data-testid="stRadio"] label:hover{background:#e8f1fb!important}
[data-testid="stDialog"] [data-testid="stModal"]{background:#f7f9fc!important}
[data-testid="stAlert"]{border-color:#d8e4f0!important}

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
    with st.expander("OTEVŘÍT EXISTUJÍCÍ PROJEKT · .cdproj",expanded=False):
        uploaded_project=st.file_uploader("Projekt COVERAGEDIAGRAMS",type=["cdproj"],
                                          key="ws_project_upload")
        if uploaded_project is not None and st.button("NAČÍST PROJEKT",key="ws_project_load"):
            try:
                result,meta=load_project(uploaded_project.getvalue())
                _config_state_from_project(result["config"])
                st.session_state["result"]=result
                st.session_state["obstacles"]=meta.get("obstacles",[])
                st.session_state["ws_levels"]=meta.get("levels",[])
                st.session_state["ws_map_revision"]=st.session_state.get("ws_map_revision",0)+1
                st.session_state["ws_viewport"]={
                    "lat":result["config"].lat,"lng":result["config"].lon,"zoom":8}
                st.rerun()
            except (ValueError,KeyError,TypeError) as exc:
                st.error(f"Projekt nelze načíst: {exc}")
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
        _calculate_coverage()


def _calculate_coverage():
    """Detailed, live, source-aware status for the synchronous coverage engine."""
    started=time.perf_counter()
    events=[]
    api_key=""
    def elapsed():
        return f"{time.perf_counter()-started:.1f} s"

    with st.status("⏳ RADAR ENGINE · Zahajuji výpočet…",
                   state="running",expanded=True) as panel:
        live_log=st.empty()
        def log(message):
            stamp=datetime.now().strftime("%H:%M:%S")
            events.append(f"[{stamp}] {message}")
            # Code log re-renders after actual engine callbacks; no invented percentages.
            live_log.code("\n".join(events[-18:]),language=None)
        def phase(title):
            panel.update(label=f"⏳ {title} · {elapsed()}",
                         state="running",expanded=True)
            log(title)
        def report(message,*args):
            # Core download/sample callbacks run as data actually arrive.
            msg=str(message).strip()
            if api_key:
                msg=msg.replace(api_key,"[API KEY]")
            if msg and (not events or msg not in events[-1]):
                log(msg[:260])
        try:
            phase("Kontroluji parametry radaru")
            c=_cfg()
            c.validate()
            az,distance=core.axes(c)
            samples=len(az)*len(distance)
            log(f"Radar: {c.radar_mode} · {c.lat:.6f}°, {c.lon:.6f}°")
            log(f"Výpočetní síť: {len(az)} azimutů × {len(distance)} vzdáleností = {samples:,} vzorků")
            if samples>250000:
                raise ValueError("Výpočet přesahuje 250 000 vzorků. Zvětši krok.")

            source=st.session_state.get("ws_source","OpenTopography")
            if source=="DEM soubor":
                phase("Čtu nahraný digitální model terénu")
                uploaded=st.session_state.get("ws_dem")
                if uploaded is None:
                    raise ValueError("Nahraj DEM soubor v nastavení radaru.")
                with tempfile.TemporaryDirectory(prefix="cd_workspace_") as work:
                    path=Path(work)/("terrain"+Path(uploaded.name).suffix.lower())
                    content=uploaded.getvalue()
                    path.write_bytes(content)
                    log(f"Soubor: {uploaded.name} · {len(content)/1048576:.1f} MiB")
                    phase("Vzorkuji DEM podél radarových paprsků")
                    terrain,ground=core.sample(path,c,report)
                    provenance="DEM upload · SHA256 "+hashlib.sha256(content).hexdigest()
            else:
                phase("Připravuji spojení s OpenTopography")
                import os
                api_key=os.environ.get("OPENTOPOGRAPHY_API_KEY","")
                if not api_key:
                    try:
                        api_key=str(st.secrets.get("OPENTOPOGRAPHY_API_KEY",""))
                    except (FileNotFoundError,KeyError,OSError):
                        pass
                if not api_key:
                    raise ValueError("OpenTopography vyžaduje OPENTOPOGRAPHY_API_KEY ve Streamlit Secrets.")
                dataset=st.session_state.get("ws_dataset","COP30")
                log(f"DEM: OpenTopography · {dataset} · vyžádaná oblast kolem radaru")
                phase("Stahuji digitální model terénu")
                path=core.download(c,api_key,dataset,report)
                phase("Vzorkuji terén do radarové mřížky")
                terrain,ground=core.sample(path,c,report)
                provenance="OpenTopography · "+dataset

            log(f"Výška stanoviště: {ground:.1f} m AMSL")
            phase("Počítám radarový horizont a výškové krytí")
            solve_started=time.perf_counter()
            result=core.solve(c,terrain,ground,_pattern(c))
            log(f"Výpočet krytí dokončen · {time.perf_counter()-solve_started:.1f} s")

            obstacles=st.session_state.get("obstacles",[])
            phase(f"Započítávám překážky · {len(obstacles)} objektů")
            apply_obstacles(result,obstacles)
            result["obstacles_signature"]=obstacle_signature(obstacles)
            log("Překážky byly promítnuty do výsledné geometrie.")

            phase("Ukládám výsledky a připravuji mapové vrstvy")
            result.update(source=provenance,
                          completed_at=datetime.now(timezone.utc).isoformat(),
                          duration_s=round(time.perf_counter()-started,3))
            st.session_state.result=result
            st.session_state.geometry={}
            st.session_state["ws_map_revision"]=st.session_state.get("ws_map_revision",0)+1
            st.session_state["ws_result_notice"]="Krytí úspěšně vypočteno."
            st.session_state["ws_next_section"]="MAPA"
            log(f"Hotovo · {elapsed()} · data jsou připravena v mapě")
            panel.update(label=f"✅ RADAR ENGINE · Hotovo za {elapsed()}",
                         state="complete",expanded=True)
        except Exception as exc:
            message=str(exc)
            if api_key:
                message=message.replace(api_key,"[API KEY]")
            log("CHYBA: "+message[:340])
            panel.update(label=f"⚠️ RADAR ENGINE · Výpočet se nezdařil · {elapsed()}",
                         state="error",expanded=True)
            st.error(message[:340])
            return

    st.success("Výpočet dokončen. Přepni do MAPA pro zobrazení letových hladin.")
    if st.button("ZOBRAZIT V MAPĚ",type="primary",key="ws_show_result_map",
                 use_container_width=True):
        st.session_state["ws_next_section"]="MAPA"
        st.rerun()


def _focused_obstacle_controls(catalog,manual):
    """Focused editor opened by a polygon click, before the full tables."""
    from obstacles import validate_obstacle
    focus=st.session_state.get("ws_selected_obstacle")
    if not focus:
        return
    kind=focus.get("kind")
    identifier=focus.get("id")
    if kind=="catalog":
        match=next((i for i,obj in enumerate(catalog) if obj["id"]==identifier),None)
        if match is None:return
        obj=catalog[match]
        category=obj.get("category","Objekt")
        source=obj.get("source","")
    elif kind=="manual":
        try:index=int(identifier)
        except (ValueError,TypeError):return
        if not 0<=index<len(manual):return
        obj=manual[index]
        category="Vlastní polygon"
        source="Uživatel"
    else:
        return
    token=focus.get("token","focused").replace("-","_").replace(".","_")
    st.markdown("### 📍 VYBRANÁ PŘEKÁŽKA")
    st.info(f"**{obj.get('name','Překážka')}** · {category} · {source}. "
            "Příslušný řádek je označen symbolem ▶ v tabulce níže.")
    name=st.text_input("Název vybraného objektu",
                       value=str(obj.get("name","Překážka")),
                       key=f"ws_focus_name_{token}")
    height=st.number_input("Výška [m AGL] · 0 = neznámá",
                           min_value=0.0,max_value=1000.0,step=1.0,
                           value=float(obj.get("height_m") or 0),
                           key=f"ws_focus_height_{token}")
    enabled=True
    if kind=="catalog":
        enabled=st.checkbox("Zahrnout do výpočtu",
                            value=bool(obj.get("enabled")),
                            key=f"ws_focus_enabled_{token}")
    left,right=st.columns([2,1],gap="small")
    with left:
        save=st.button("ULOŽIT VYBRANOU PŘEKÁŽKU",type="primary",
                       use_container_width=True,key=f"ws_focus_save_{token}")
    with right:
        delete=st.button("ODSTRANIT",use_container_width=True,
                         key=f"ws_focus_delete_{token}")
    if not save and not delete:return
    try:
        site=_cfg_site()
        if kind=="catalog":
            updated=[dict(x) for x in catalog]
            if delete:
                deleted_ids=set(st.session_state.get("ws_imported_deleted_ids",[]))
                deleted_ids.add(identifier)
                st.session_state["ws_imported_deleted_ids"]=list(deleted_ids)
                updated.pop(match)
            else:
                changed=updated[match]
                changed["name"]=name.strip() or changed["name"]
                changed["height_m"]=height if height>.0 else None
                changed["enabled"]=bool(enabled)
                if changed["enabled"] and changed["height_m"] is None:
                    raise ValueError("Pro výpočet musíš nejprve doplnit výšku.")
                if changed["enabled"]:
                    validate_obstacle({"kind":"polygon",
                        "coordinates":changed["coordinates"],
                        "height_m":changed["height_m"]},*site)
            active,invalid=synchronize(st.session_state.get("obstacles",[]),
                                       updated,*site,auto_enable=False)
            st.session_state["ws_imported_catalog"]=updated
            st.session_state["obstacles"]=active
        else:
            updated=[dict(x) for x in manual]
            if delete:
                updated.pop(index)
            else:
                updated[index]["name"]=name.strip() or updated[index]["name"]
                if height<=0:
                    raise ValueError("Vlastní překážka musí mít kladnou výšku.")
                updated[index]["height_m"]=height
                validate_obstacle(updated[index],*site)
            active,invalid=synchronize(updated,catalog,*site,auto_enable=False)
            st.session_state["obstacles"]=active
        st.session_state["ws_obstacle_revision"]=st.session_state.get("ws_obstacle_revision",0)+1
        st.session_state["ws_selected_obstacle"]=None
        st.rerun()
    except (ValueError,TypeError,KeyError) as exc:
        st.error(f"Úpravu nelze uložit: {exc}")


@st.dialog("PŘEKÁŽKY / Upravit a odstranit",width="large")
def obstacles_dialog():
    """One editor for drawn obstacles and automatically loaded geodata."""
    import pandas as pd
    from obstacles import validate_obstacle

    catalog=st.session_state.setdefault("ws_imported_catalog",[])
    all_items=st.session_state.setdefault("obstacles",[])
    manual=[x for x in all_items if not x.get("catalog_id")]
    active_count=sum(bool(x.get("enabled")) for x in catalog)
    st.caption("Načtené polygony a turbíny se zobrazují automaticky. "
               "Neznámou výšku můžeš doplnit ručně; jen aktivní překážky "
               "se známou výškou vstupují do výpočtu.")
    a,b,d=st.columns(3)
    a.metric("Načtené objekty",len(catalog))
    b.metric("Aktivní pro výpočet",active_count+len(manual))
    d.metric("Vlastní polygony",len(manual))
    focus=st.session_state.get("ws_selected_obstacle") or {}
    _focused_obstacle_controls(catalog,manual)
    manual_first=focus.get("kind")=="manual"
    tabs=st.tabs(["VLASTNÍ PŘEKÁŽKY","NAČTENÉ GEODATA"] if manual_first
                 else ["NAČTENÉ GEODATA","VLASTNÍ PŘEKÁŽKY"])
    imported_tab=tabs[1] if manual_first else tabs[0]
    manual_tab=tabs[0] if manual_first else tabs[1]
    with imported_tab:
        if not catalog:
            st.info("Geodata zatím nejsou načtená. V sekci MAPA otevři Geodata / okolní překážky.")
        else:
            st.caption("Výška z OSM je informativní. Prázdná hodnota znamená neznámou výšku, "
                       "nikoli nulovou. Výpočet podporuje maximálně 1000 aktivních překážek.")
            types=sorted(set(x["category"] for x in catalog))
            # Clicking a polygon resets filters so its row is always visible.
            if focus.get("kind")=="catalog":
                st.session_state["ws_catalog_kind"]="Vše"
                st.session_state["ws_catalog_search"]=""
                st.session_state["ws_catalog_page"]=1
            left,right=st.columns([1,2])
            with left:
                category=st.selectbox("Kategorie",["Vše"]+types,key="ws_catalog_kind")
            with right:
                query=st.text_input("Hledat název / zdroj",key="ws_catalog_search")
            query=query.strip().casefold()
            matches=[i for i,x in enumerate(catalog)
                     if (category=="Vše" or x["category"]==category)
                     and (not query or query in
                          (x["name"]+" "+x["source"]).casefold())]
            # Keep the clicked item at the very top with a visible marker.
            selected_id=focus.get("id") if focus.get("kind")=="catalog" else None
            if selected_id:
                matches.sort(key=lambda i:0 if catalog[i]["id"]==selected_id else 1)
            page_size=75
            pages=max(1,(len(matches)+page_size-1)//page_size)
            if int(st.session_state.get("ws_catalog_page",1))>pages:
                st.session_state["ws_catalog_page"]=1
            page=st.number_input(f"Strana · {len(matches)} objektů",min_value=1,
                                 max_value=pages,value=1,step=1,key="ws_catalog_page")
            indexes=matches[(page-1)*page_size:page*page_size]
            current=[catalog[i] for i in indexes]
            table=pd.DataFrame([{
                "Výběr":"▶ VYBRÁNO" if x["id"]==selected_id else "",
                "Název":x["name"],
                "Typ":x["category"],
                "Zdroj":x["source"],
                "Výška [m AGL]":x["height_m"],
                "Výpočet":bool(x["enabled"]),
                "Smazat":False,
            } for x in current])
            rev=st.session_state.get("ws_obstacle_revision",0)
            edited=st.data_editor(
                table,key=f"ws_imported_table_{rev}_{page}_{category}_{query}",
                hide_index=True,use_container_width=True,
                column_config={
                    "Výběr":st.column_config.TextColumn(disabled=True,width="small"),
                    "Název":st.column_config.TextColumn(required=True),
                    "Typ":st.column_config.TextColumn(disabled=True),
                    "Zdroj":st.column_config.TextColumn(disabled=True),
                    "Výška [m AGL]":st.column_config.NumberColumn(
                        min_value=.1,max_value=1000.,step=1.,required=False),
                    "Výpočet":st.column_config.CheckboxColumn(),
                    "Smazat":st.column_config.CheckboxColumn(),
                })
            if st.button("ULOŽIT ÚPRAVY / ODSTRANĚNÍ",type="primary",
                         use_container_width=True,key="ws_catalog_save"):
                try:
                    import math
                    changed={}
                    deleted=set()
                    for row_idx,record in edited.iterrows():
                        index=indexes[row_idx]
                        item=dict(catalog[index])
                        if bool(record["Smazat"]):
                            deleted.add(index)
                            continue
                        h=record["Výška [m AGL]"]
                        item["height_m"]=None if pd.isna(h) else float(h)
                        item["name"]=str(record["Název"]).strip() or item["name"]
                        item["enabled"]=bool(record["Výpočet"])
                        if item["enabled"]:
                            if item["height_m"] is None:
                                raise ValueError(f"{item['name']}: vyplň nejprve výšku.")
                            validate_obstacle({
                                "kind":"polygon","coordinates":item["coordinates"],
                                "height_m":item["height_m"]},*_cfg_site())
                        changed[index]=item
                    deleted_ids=set(st.session_state.get("ws_imported_deleted_ids",[]))
                    deleted_ids.update(catalog[i]["id"] for i in deleted)
                    st.session_state["ws_imported_deleted_ids"]=list(deleted_ids)
                    updated=[changed.get(i,x) for i,x in enumerate(catalog) if i not in deleted]
                    active,invalid=synchronize(all_items,updated,*_cfg_site(),
                                               auto_enable=False)
                    st.session_state["ws_imported_catalog"]=updated
                    st.session_state["obstacles"]=active
                    st.session_state["ws_obstacle_revision"]=rev+1
                    st.session_state["ws_map_revision"]=st.session_state.get("ws_map_revision",0)+1
                    st.success(f"Uloženo. Aktuálně {len(active)} aktivních výpočetních překážek.")
                    st.rerun()
                except (ValueError,TypeError,KeyError) as exc:
                    st.error(f"Nelze uložit: {exc}")

    with manual_tab:
        if not manual:
            st.info("Vlastní překážky zatím nejsou zakreslené. Přejdi do sekce PŘEKÁŽKY.")
        else:
            selected_manual=(int(focus["id"]) if focus.get("kind")=="manual"
                             and str(focus.get("id","")).isdigit() else -1)
            manual_indices=list(range(len(manual)))
            if 0<=selected_manual<len(manual):
                manual_indices.remove(selected_manual)
                manual_indices.insert(0,selected_manual)
            table=pd.DataFrame([{
                "Výběr":"▶ VYBRÁNO" if i==selected_manual else "",
                "Název":manual[i].get("name",f"Překážka {i+1}"),
                "Výška [m AGL]":float(manual[i]["height_m"]),
                "Smazat":False,
            } for i in manual_indices])
            rev=st.session_state.get("ws_obstacle_revision",0)
            edited=st.data_editor(
                table,key=f"ws_manual_table_{rev}",
                use_container_width=True,hide_index=True,
                column_config={
                    "Výběr":st.column_config.TextColumn(disabled=True,width="small"),
                    "Název":st.column_config.TextColumn(required=True),
                    "Výška [m AGL]":st.column_config.NumberColumn(
                        min_value=.1,max_value=1000.,step=1.),
                    "Smazat":st.column_config.CheckboxColumn(),
                })
            if st.button("ULOŽIT VLASTNÍ PŘEKÁŽKY",type="primary",
                         use_container_width=True,key="ws_manual_save"):
                updated=[]
                try:
                    for i,row in edited.iterrows():
                        if bool(row["Smazat"]):
                            continue
                        item=dict(manual[manual_indices[i]])
                        item["name"]=str(row["Název"]).strip() or item.get("name","Překážka")
                        item["height_m"]=float(row["Výška [m AGL]"])
                        validate_obstacle(item,*_cfg_site())
                        updated.append(item)
                    new_active,invalid=synchronize(updated,catalog,*_cfg_site())
                    st.session_state["obstacles"]=new_active
                    st.session_state["ws_obstacle_revision"]=rev+1
                    st.rerun()
                except (ValueError,TypeError,KeyError) as exc:
                    st.error(f"Nelze uložit: {exc}")


def _cfg_site():
    c=_cfg()
    return c.lat,c.lon


@st.dialog("NOVÁ PŘEKÁŽKA / Polygon",width="small")
def new_obstacle_dialog():
    from obstacles import validate_obstacle
    coords=st.session_state.get("ws_pending_polygon")
    if not coords:
        st.info("Nejprve nakresli polygon na hlavní mapě.")
        return
    st.caption(f"Polygon: {len(coords)} vrcholů · WGS84")
    count=len(st.session_state.setdefault("obstacles",[]))
    name=st.text_input("Název",value=f"Překážka {count+1:02d}",key="ws_polygon_name")
    height=st.number_input("Výška [m AGL]",min_value=.1,max_value=1000.,
                           value=20.,step=1.,key="ws_polygon_height")
    left,right=st.columns(2)
    with left:
        if st.button("ZRUŠIT",use_container_width=True,key="ws_polygon_cancel"):
            st.session_state.pop("ws_pending_polygon",None)
            st.session_state["ws_map_revision"]=st.session_state.get("ws_map_revision",0)+1
            st.rerun()
    with right:
        if st.button("PŘIDAT DO MAPY",type="primary",use_container_width=True,key="ws_polygon_confirm"):
            try:
                if count>=1000: raise ValueError("Nejvýše 1000 výpočetních překážek.")
                c=_cfg()
                item={"kind":"polygon","name":name.strip() or f"Překážka {count+1:02d}",
                      "coordinates":coords,"height_m":float(height)}
                validate_obstacle(item,c.lat,c.lon)
                st.session_state["obstacles"].append(item)
                st.session_state.pop("ws_pending_polygon",None)
                st.session_state["ws_obstacle_revision"]=st.session_state.get("ws_obstacle_revision",0)+1
                st.session_state["ws_map_revision"]=st.session_state.get("ws_map_revision",0)+1
                st.session_state["ws_next_section"]="MAPA"
                st.rerun()
            except (ValueError,TypeError,KeyError) as exc:
                st.error(str(exc))


@st.dialog("PROVOZ / Live a historie",width="large")
def traffic_dialog():
    simulation_tab(st.session_state.get("result"),st.session_state.get("ws_levels",[3000,10000]))


@st.dialog("GEODATA / Okolní objekty",width="large")
def layers_dialog():
    """One explicit source-selection window; all loaded items share the main map."""
    from io import BytesIO, StringIO
    from zipfile import ZipFile, ZIP_DEFLATED
    import csv
    import json

    c=_cfg()
    site=(round(c.lat,5),round(c.lon,5))
    st.caption(f"Stanoviště {c.lat:.5f}°, {c.lon:.5f}° · WGS84. "
               "Data se načtou pouze po stisknutí tlačítka.")
    st.markdown("**CO CHCEŠ NAČÍST?**")
    col1,col2=st.columns(2)
    with col1:
        buildings=st.checkbox("Budovy, lesy a věže · OpenStreetMap",
                              value=True,key="ws_geo_osm")
        airports=st.checkbox("Letiště a heliporty · OurAirports",
                             value=False,key="ws_geo_airports")
    with col2:
        wind=st.checkbox("Větrné elektrárny · dataset / OSM",
                         value=True,key="ws_geo_wind")
        microsoft=st.checkbox("Microsoft Building Footprints",
                              value=False,key="ws_geo_microsoft")
    radius=st.slider("Okolí pro budovy / lesy / věže [km]",.5,10.,3.,.5,
                     key="ws_geo_radius")
    st.caption("OpenStreetMap: 0,5–10 km · větrné elektrárny: 100 km · "
               "letiště: 120 km. Data mohou být neúplná a jejich výšky nejsou ověřené.")

    if st.button("NAČÍST VYBRANÁ GEODATA",type="primary",
                 use_container_width=True,key="ws_geo_fetch"):
        if not (buildings or airports or wind or microsoft):
            st.warning("Vyber alespoň jeden datový zdroj.")
        else:
            sources=[
                ("OpenStreetMap / Overpass",buildings),
                ("Microsoft Building Footprints",microsoft),
                ("OurAirports",airports),
                ("Větrné elektrárny / offline dataset, případně OSM",wind),
            ]
            work=[name for name,enabled in sources if enabled]
            loaded=[]
            errors=[]
            completed={}
            started=time.perf_counter()
            with st.status("⏳ Připravuji načtení geodat…",expanded=True,state="running") as progress:
                st.caption(f"📍 {site[0]:.5f}°, {site[1]:.5f}° · {len(work)} zdroje · "
                           "skutečný průběh bez odhadovaných procent")
                for step,(name,enabled) in enumerate(sources,1):
                    if not enabled:
                        continue
                    current=len(completed)+1
                    progress.update(label=f"⏳ Pracuji · {current}/{len(work)} · {name}",
                                    state="running",expanded=True)
                    st.write(f"**⏳ {name}** — navazuji spojení / zpracovávám data…")
                    t0=time.perf_counter()
                    try:
                        if name.startswith("OpenStreetMap"):
                            fetched=env.fetch_osm(*site,radius)
                            loaded.extend(fetched)
                            count=len(fetched)
                            detail=f"budovy, lesy, věže · {radius:g} km"
                        elif name.startswith("Microsoft"):
                            from microsoft_buildings import fetch_microsoft
                            fetched=fetch_microsoft(*site,radius)
                            loaded.extend(fetched)
                            count=len(fetched)
                            detail=f"budovy · {radius:g} km"
                        elif name=="OurAirports":
                            fetched=aviation.nearby(*site,120)
                            st.session_state["ws_airports"]=fetched
                            count=len(fetched)
                            detail="letiště a heliporty · 120 km"
                        else:
                            fetched=load_wind_turbines(*site)
                            st.session_state["ws_wind_data"]=fetched
                            count=len(fetched)
                            detail="větrné elektrárny · 100 km"
                        completed[name]=count
                        st.write(f"✅ {name}: **{count:,} objektů** · {detail} · "
                                 f"{time.perf_counter()-t0:.1f} s")
                    except Exception as exc:
                        reason=str(exc)[:155]
                        errors.append(f"{name}: {reason}")
                        completed[name]=None
                        st.write(f"⚠️ {name}: nepodařilo se načíst · "
                                 f"{time.perf_counter()-t0:.1f} s")
                        st.caption(reason)
                if buildings or microsoft:
                    st.session_state["ws_environment"]=loaded[:env.MAX_ENVIRONMENT_ITEMS]
                st.session_state["ws_geodata_site"]=site
                st.session_state["ws_geodata_errors"]=errors
                # Loaded polygons and turbines become editable immediately.
                # Keep prior catalog edits for matching items across repeated fetches.
                previous={x["id"]:x for x in st.session_state.get("ws_imported_catalog",[])}
                deleted_ids=set(st.session_state.get("ws_imported_deleted_ids",[]))
                new_catalog=[x for x in catalog_from_data(
                    st.session_state.get("ws_environment",[]),
                    st.session_state.get("ws_wind_data",[]))
                    if x["id"] not in deleted_ids]
                for item in new_catalog:
                    old=previous.get(item["id"])
                    if old:
                        item.update(name=old["name"],height_m=old["height_m"],
                                    enabled=old["enabled"])
                    elif item.get("height_m") is not None:
                        item["enabled"]=True
                current_manual=st.session_state.setdefault("obstacles",[])
                # New known-height objects are enabled automatically; previous
                # user decisions and deletions are retained between imports.
                actual,invalid=synchronize(current_manual,new_catalog,*site,
                                           auto_enable=False)
                st.session_state["ws_imported_catalog"]=new_catalog
                st.session_state["obstacles"]=actual
                st.session_state["ws_obstacle_revision"]=st.session_state.get("ws_obstacle_revision",0)+1
                total=sum(v for v in completed.values() if v is not None)
                elapsed=time.perf_counter()-started
                if errors:
                    progress.update(
                        label=f"⚠️ Hotovo s upozorněním · {total:,} objektů · {elapsed:.1f} s",
                        state="error",expanded=True)
                else:
                    progress.update(
                        label=f"✅ Hotovo · {total:,} objektů · {elapsed:.1f} s",
                        state="complete",expanded=False)
            st.caption("Načtené polygony jsou automaticky přidané do PŘEKÁŽKY → Upravit / odstranit. "
                       "Objekty se známou výškou lze zahrnout do výpočtu (max. 1000); "
                       "neznámé výšky zůstávají k doplnění.")

    if st.session_state.get("ws_geodata_site")!=site:
        if st.session_state.get("ws_geodata_site"):
            st.warning("Geodata jsou z jiného stanoviště. Načti je znovu pro aktuální radar.")
        return

    environment_items=st.session_state.get("ws_environment",[])
    wind_items=st.session_state.get("ws_wind_data",[])
    airport_items=st.session_state.get("ws_airports",[])
    a,b,d=st.columns(3)
    a.metric("Budovy / lesy / věže",len(environment_items))
    b.metric("Větrné elektrárny",len(wind_items))
    d.metric("Letiště",len(airport_items))

    st.markdown("**ZOBRAZENÍ V HLAVNÍ MAPĚ**")
    visibility=st.columns(3)
    with visibility[0]:
        st.checkbox("Objekty OSM / MS",value=True,key="ws_geo_show_environment")
    with visibility[1]:
        st.checkbox("Turbíny",value=True,key="ws_geo_show_wind")
    with visibility[2]:
        st.checkbox("Letiště",value=True,key="ws_geo_show_airports")

    if environment_items or wind_items or airport_items:
        buffer=BytesIO()
        with ZipFile(buffer,"w",ZIP_DEFLATED) as archive:
            if environment_items:
                archive.writestr("geodata/objects.geojson",env.geojson_bytes(environment_items))
                archive.writestr("geodata/objects.kml",env.kml_bytes(environment_items))
            if airport_items:
                archive.writestr("geodata/airports.geojson",aviation.geojson_bytes(airport_items))
                archive.writestr("geodata/airports.csv",aviation.csv_bytes(airport_items))
            if wind_items:
                columns=["lat","lon","name","height","hub_height","rotor","distance_km","az","osm_id"]
                out=StringIO()
                writer=csv.DictWriter(out,fieldnames=columns,extrasaction="ignore")
                writer.writeheader()
                writer.writerows(wind_items)
                archive.writestr("geodata/wind_turbines.csv",out.getvalue().encode("utf-8-sig"))
                archive.writestr("geodata/wind_turbines.geojson",
                    json.dumps({"type":"FeatureCollection","features":[
                        {"type":"Feature","geometry":{"type":"Point",
                          "coordinates":[x["lon"],x["lat"]]},
                         "properties":{k:v for k,v in x.items() if k not in ("lat","lon")}}
                        for x in wind_items]},ensure_ascii=False).encode("utf-8"))
        st.download_button("STÁHNOUT NAČTENÁ GEODATA · ZIP",
                           data=buffer.getvalue(),file_name="COVERAGEDIAGRAMS_geodata.zip",
                           mime="application/zip",use_container_width=True,key="ws_geodata_download")
    st.caption("Objekty se známou výškou a validním polygonem se zařadí do výpočtu automaticky "
               "do limitu 1000; ostatní zůstávají editovatelné, ale zatím pouze informativní.")


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


def _draw_map_folium():
    result=st.session_state.get("result")
    # Editing an uncalculated site must not be confused with the old result's location.
    configured=_cfg()
    c=result["config"] if result is not None else configured
    view=st.session_state.get("ws_viewport")
    center=[view["lat"],view["lng"]] if view else [configured.lat,configured.lon]
    zoom=view["zoom"] if view else (8 if result else 9)
    m=folium.Map(location=center,zoom_start=zoom,
                 tiles=None,control_scale=True,prefer_canvas=True,
                 zoom_animation=False,fade_animation=False)
    for name,provider in _workspace_basemaps().items():
        folium.TileLayer(provider["url"],name=name,attr=provider["attribution"],
                         max_zoom=provider["max_zoom"],overlay=False,
                         show=name=="OpenStreetMap").add_to(m)
    if st.session_state.get("ws_openaip",True):
        add_openaip_map(m)
    if result is not None and st.session_state.get("ws_show_coverage",True):
        mode=st.session_state.get("ws_display_mode","Jedna hladina")
        levels=[x for x in st.session_state.get("ws_levels",[3000,10000])
                if x in core.flight_levels_for(c.radar_mode)]
        if mode=="Cíl":active=[None]
        elif mode=="Porovnání":active=st.session_state.get("ws_comparison",levels[:3])
        elif levels:active=[st.session_state.get("ws_map_level",levels[0])]
        else:active=[]
        for level in active:
            if level is not None and level not in core.flight_levels_for(c.radar_mode):
                continue
            geo=coverage_geojson(result,level)
            if geo.get("features"):
                color="#247ad3" if level is None else to_hex(core.level_color(level))
                layer=folium.FeatureGroup(name="Krytí cíle" if level is None else core.level_label(level))
                opacity=st.session_state.get("ws_map_opacity",.42)
                folium.GeoJson(geo,style_function=lambda feature,color=color,opacity=opacity:
                               {"color":color,"weight":1.5,"fillColor":color,
                                "fillOpacity":opacity}).add_to(layer)
                layer.add_to(m)
    # Draw editable site configuration and obstacles independently from the
    # last calculated result. Otherwise the map appears stale before rerun.
    folium.Marker([configured.lat,configured.lon],
                  tooltip=f"{configured.radar_mode} · stanoviště radaru",
                  icon=folium.Icon(color="blue",icon="signal")).add_to(m)
    if result is not None and (abs(c.lat-configured.lat)>1e-6 or abs(c.lon-configured.lon)>1e-6):
        folium.CircleMarker([c.lat,c.lon],radius=5,color="#24a69e",
                            tooltip="Stanoviště posledního výpočtu").add_to(m)
    obstacle_layer=folium.FeatureGroup(
        name=f"Překážky · {len(st.session_state.get('obstacles',[]))}",show=True)
    for item in st.session_state.get("obstacles",[]):
        folium.Polygon(obstacle_polygon(item,configured.lat,configured.lon),
                       color="#e87848",weight=2,fill=True,fill_opacity=.32,
                       tooltip=f"{item.get('name','Překážka')} · {item['height_m']:g} m AGL"
                       ).add_to(obstacle_layer)
    obstacle_layer.add_to(m)
    catalog=st.session_state.get("ws_imported_catalog")
    if catalog is not None:
        geodata_layer=folium.FeatureGroup(name="Načtená geodata",show=True)
        colors={**env.COLORS,"Wind":"#0d9cb0"}
        for item in catalog[:6000]:
            folium.Polygon(item["coordinates"],color=colors.get(item["category"],"#859db0"),
                           weight=1,fill=True,fill_opacity=.18,
                           tooltip=item["name"]).add_to(geodata_layer)
        geodata_layer.add_to(m)
    elif st.session_state.get("ws_environment"):
        env.layer_group(m,st.session_state["ws_environment"],"Budovy / lesy / věže")
    if st.session_state.get("ws_airports"):
        aviation.add_airports(m,st.session_state["ws_airports"])
    if st.session_state.get("ws_canopy") is not None:
        canopy.add_layer(m,st.session_state["ws_canopy"])

    if st.session_state.get("ws_live_adsb",False):
        records=st.session_state.get("ws_traffic_snapshot",[])
        site=st.session_state.get("ws_traffic_site")
        if site==(round(configured.lat,5),round(configured.lon,5)):
            add_traffic_layer(m,records)
    tool=_map_tool()
    if tool=="Polygon":
        Draw(export=False,
             draw_options={"polyline":False,"rectangle":False,"circle":False,
                           "circlemarker":False,"marker":False,
                           "polygon":{"allowIntersection":False,"showArea":True}},
             edit_options={"edit":False,"remove":False}).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    Fullscreen().add_to(m)
    MeasureControl(primary_length_unit="kilometers").add_to(m)
    event=st_folium(m,height=730,use_container_width=True,
              key=f"ws_map_{st.session_state.get('ws_map_revision',0)}",
              returned_objects=["last_clicked","last_active_drawing","center","zoom"])
    if event:
        current=event.get("center")
        current_zoom=event.get("zoom")
        if isinstance(current,dict) and current_zoom is not None:
            st.session_state["ws_viewport"]={
                "lat":float(current["lat"]),"lng":float(current["lng"]),
                "zoom":int(current_zoom)}
        if tool=="Radar" and event.get("last_clicked"):
            clicked=event["last_clicked"]
            try:
                lat,lon=coordinates_from_map_click(clicked)
                old=(float(st.session_state.get("ws_lat",50.034)),
                     float(st.session_state.get("ws_lon",15.781)))
                if old!=(lat,lon):
                    st.session_state["ws_lat"]=lat
                    st.session_state["ws_lon"]=lon
                    st.session_state["ws_next_section"]="MAPA"
                    st.session_state["ws_map_revision"]=st.session_state.get("ws_map_revision",0)+1
                    st.rerun()
            except (TypeError,ValueError,KeyError) as exc:
                st.warning(f"Neplatné místo radaru: {exc}")
        if tool=="Polygon":
            drawing=event.get("last_active_drawing")
            if drawing and drawing.get("geometry",{}).get("type")=="Polygon":
                ring=drawing["geometry"]["coordinates"][0]
                coords=[[float(pair[1]),float(pair[0])] for pair in ring[:-1]]
                signature=tuple(tuple(pt) for pt in coords)
                if len(coords)>=3 and signature!=st.session_state.get("ws_last_polygon"):
                    st.session_state["ws_last_polygon"]=signature
                    st.session_state["ws_pending_polygon"]=coords
                    new_obstacle_dialog()
    st.session_state["ws_map_html"]=m.get_root().render().encode("utf-8")

def _draw_map():
    """Render one persistent JS Leaflet instance; Python only sends changed data."""
    import json
    from urllib.parse import quote
    from aviation_basemap import configured_key
    from persistent_leaflet import show_persistent_map

    result=st.session_state.get("result")
    configured=_cfg()
    c=result["config"] if result is not None else configured

    # Map always stays mounted under a stable key; levels are incremental GeoJSON.
    active=[]
    if result is not None and st.session_state.get("ws_show_coverage",True):
        mode=st.session_state.get("ws_display_mode","Jedna hladina")
        available=[ft for ft in st.session_state.get("ws_levels",[3000,10000])
                   if ft in core.flight_levels_for(c.radar_mode)]
        if not available:
            available=list(core.flight_levels_for(c.radar_mode))
        if mode=="Cíl":
            active=[None]
        elif mode=="Porovnání":
            active=[ft for ft in st.session_state.get("ws_comparison",[]) if ft in available]
        elif available:
            wanted=st.session_state.get("ws_map_level",available[0])
            active=[wanted if wanted in available else available[0]]

    coverage=[]
    for level in active:
        if level not in st.session_state.setdefault("geometry",{}):
            st.session_state.geometry[level]=coverage_geojson(result,level)
        coverage.append({
            "geojson":st.session_state.geometry[level],
            "color":"#247ad3" if level is None else to_hex(core.level_color(level)),
        })

    obstacle_data=[]
    # A downloaded object's catalog polygon is already rendered in the
    # environment layer; don't render a second clickable duplicate.
    manual_obstacles=[o for o in st.session_state.get("obstacles",[])
                      if not o.get("catalog_id")]
    for index,item in enumerate(manual_obstacles):
        obstacle_data.append({
            "id":str(index),
            "name":str(item.get("name","Překážka")),
            "height_m":float(item["height_m"]),
            "coordinates":obstacle_polygon(item,configured.lat,configured.lon),
        })
    environment_data=[]
    catalog=st.session_state.get("ws_imported_catalog")
    if catalog is not None:
        # Deleted objects disappear from the map, including wind polygons.
        palette={**env.COLORS,"Wind":"#0d9cb0"}
        for item in catalog[:12000]:
            if item.get("coordinates"):
                environment_data.append({
                    "id":str(item["id"]),
                    "coordinates":item["coordinates"],
                    "color":palette.get(item.get("category"),"#8097aa"),
                    "name":str(item.get("name","Objekt")),
                })
    else:
        for item in st.session_state.get("ws_environment",[])[:12000]:
            if item.get("coordinates"):
                environment_data.append({
                    "coordinates":item["coordinates"],
                    "color":env.COLORS.get(item.get("kind"),"#8097aa"),
                    "name":str(item.get("name","Objekt")),
                })

    for airport in st.session_state.get("ws_airports",[])[:350]:
        environment_data.append({
            "type":"point","lat":float(airport["lat"]),"lon":float(airport["lon"]),
            "color":"#4a83d1",
            "name":str(airport.get("icao") or "")+" · "+str(airport.get("name") or "Letiště"),
        })


    basemaps=[
        {"name":name,"url":provider["url"],
         "attribution":provider["attribution"],
         "max_zoom":provider["max_zoom"]}
        for name,provider in core.BASEMAP_PROVIDERS.items()
    ]
    key=configured_key() if st.session_state.get("ws_openaip",True) else None
    openaip={"enabled":bool(key),
             "url":("https://api.tiles.openaip.net/api/data/openaip/"
                    "{z}/{x}/{y}.png?apiKey="+quote(key,safe="")) if key else ""}
    # Browser-side profile sampled from the same DEM matrices as the solver.
    profile=None
    if result is not None:
        arr=np.asarray(result["terrain"],dtype=float)
        lower=np.asarray(result["lower"],dtype=float)
        az=np.asarray(result["az"],dtype=float)
        dist=np.asarray(result["distance"],dtype=float)/1000.
        stride=max(1,int(np.ceil(len(dist)/280)))
        az_stride=max(1,int(np.ceil(len(az)/720)))
        def finite_values(a):
            return np.where(np.isfinite(a),np.round(a,1),None).tolist()
        profile={
            "site":[float(result["config"].lat),float(result["config"].lon)],
            "az":np.round(az[::az_stride],3).tolist(),
            "distance":np.round(dist[::stride],4).tolist(),
            "terrain":finite_values(arr[::az_stride,::stride]),
            "lower":finite_values(lower[::az_stride,::stride]),
            "maxRangeKm":float(result["config"].range_km),
            "version":str(result.get("completed_at","")),
        }
    alpha=st.session_state.get("ws_map_opacity",.42)
    import hashlib
    def signature(items):
        return hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False,
                                          default=str).encode("utf-8")).hexdigest()[:20]
    payload={
        "center":[configured.lat,configured.lon],
        "zoom":8 if result else 9,
        "radar":{"lat":configured.lat,"lon":configured.lon,
                 "label":configured.radar_mode+" · RADAR"},
        "basemaps":basemaps,
        "openaip":openaip,
        "theme":st.session_state.get("ws_daynight","DAY"),
        "tool":_map_tool(),
        "live":bool(st.session_state.get("ws_live_adsb",False)),
        "coverage":coverage,
        "opacity":alpha,
        "coverageVersion":signature([active,alpha,
                                      result.get("completed_at") if result else None]),
        "obstacles":obstacle_data,
        "obstaclesVersion":signature(obstacle_data),
        "environment":environment_data,
        "environmentVersion":signature(environment_data),
        "profile":profile,
    }
    action=show_persistent_map(payload)
    if isinstance(action,dict):
        event_id=str(action.get("id",""))
        if event_id and event_id != st.session_state.get("ws_last_map_action_id"):
            st.session_state["ws_last_map_action_id"]=event_id
            if action.get("type")=="edit_obstacle":
                kind=str(action.get("kind",""))
                identifier=str(action.get("id",""))
                valid=(kind=="manual" and identifier.isdigit() and
                       int(identifier)<len(manual_obstacles))
                valid=valid or (kind=="catalog" and any(
                    x["id"]==identifier for x in st.session_state.get("ws_imported_catalog",[])))
                if valid:
                    st.session_state["ws_selected_obstacle"]={
                        "kind":kind,"id":identifier,"token":event_id}
                    obstacles_dialog()
            elif action.get("type")=="radar" and payload["tool"]=="Radar":
                try:
                    lat,lon=coordinates_from_map_click({
                        "lat":action["lat"],"lng":action["lon"]})
                    st.session_state["ws_lat"]=lat
                    st.session_state["ws_lon"]=lon
                    st.session_state["ws_next_section"]="MAPA"
                    st.rerun()
                except (ValueError,TypeError,KeyError) as exc:
                    st.warning("Neplatné stanoviště radaru: "+str(exc))
            elif action.get("type")=="polygon" and payload["tool"]=="Polygon":
                try:
                    coords=[[float(y),float(x)] for y,x in action["coordinates"]]
                    if len(coords)>=3:
                        st.session_state["ws_pending_polygon"]=coords
                        new_obstacle_dialog()
                except (ValueError,TypeError,KeyError) as exc:
                    st.warning("Neplatný polygon: "+str(exc))
    # HTML ZIP export is still available from the established Folium engine.
    # Do not overwrite it with a placeholder or untrusted client data.


@st.cache_data(ttl=12,show_spinner=False)
def _traffic_cached(lat,lon):
    """Avoid repeated API calls when Leaflet generates interaction reruns."""
    return fetch_snapshot(lat,lon,100)


@st.fragment(run_every="15s")
def _live_map_frame():
    """Refresh only map/traffic, not the surrounding workspace controls."""
    configured=_cfg()
    lat,lon=round(configured.lat,5),round(configured.lon,5)
    try:
        st.session_state["ws_traffic_snapshot"]=_traffic_cached(lat,lon)
        st.session_state["ws_traffic_site"]=(lat,lon)
    except (RuntimeError,ValueError) as exc:
        st.caption(f"ADS-B: poslední dostupný snímek · {exc}")
    _draw_map_folium()


def _workspace_basemaps():
    """Short, dependable basemap menu; OpenAIP stays a separate overlay."""
    names=("OpenStreetMap","OpenTopoMap","Satelitní · Esri")
    return {name:core.BASEMAP_PROVIDERS[name] for name in names}


def _map_tool():
    """Map editing follows the active workspace section automatically."""
    return {
        "MAPA": "Prohlížení",
        "RADAR": "Radar",
        "PŘEKÁŽKY": "Polygon",
    }.get(st.session_state.get("ws_section","MAPA"),"Prohlížení")


def _restore_sidebar_preferences():
    """Keep options while switching conditional sidebar sections.

    Streamlit removes widget keys when widgets aren't rendered; copy their
    values to independent session-state keys before leaving the MAPA section.
    """
    keys=("ws_show_coverage","ws_display_mode","ws_map_level",
          "ws_comparison","ws_map_opacity","ws_openaip",
          "ws_live_adsb","ws_show_wind","ws_daynight")
    for key in keys:
        saved="_persist_"+key
        if key in st.session_state:
            st.session_state[saved]=st.session_state[key]
        elif saved in st.session_state:
            st.session_state[key]=st.session_state[saved]


def _step_flight_level(direction):
    """Step between computed levels without rebuilding the Leaflet map."""
    result=st.session_state.get("result")
    if result is None:
        return
    allowed=tuple(core.flight_levels_for(result["config"].radar_mode))
    levels=[int(ft) for ft in st.session_state.get("ws_levels",[]) if ft in allowed]
    if not levels:
        levels=list(allowed)
    levels=sorted(set(levels))
    if not levels:
        return
    current=st.session_state.get("ws_map_level",levels[0])
    try:
        index=levels.index(current)
    except ValueError:
        index=0
    st.session_state["ws_map_level"]=levels[(index+direction)%len(levels)]


def _select_comparison_levels(select_all):
    result=st.session_state.get("result")
    if result is None:
        return
    allowed=tuple(core.flight_levels_for(result["config"].radar_mode))
    levels=sorted(set(int(ft) for ft in st.session_state.get("ws_levels",[]) if ft in allowed))
    if not levels:
        levels=list(allowed)
    st.session_state["ws_comparison"]=levels if select_all else []


def render_workspace():
    """One persistent map; three task-oriented sections in the 400px sidebar."""
    previous=st.session_state.get("result")
    if previous is not None and "ws_radar" not in st.session_state:
        _config_state_from_project(previous["config"])
        st.session_state["ws_levels"]=list(st.session_state.get("levels",[3000,10000]))

    _restore_sidebar_preferences()

    next_section=st.session_state.pop("ws_next_section",None)
    if next_section in ("MAPA","RADAR","PŘEKÁŽKY"):
        st.session_state["ws_section"]=next_section

    st.markdown(STYLES,unsafe_allow_html=True)
    st.markdown("""
    <style>
      [data-testid="stSidebar"]{width:400px!important;min-width:400px!important;
          background:#ffffff!important;border-right:1px solid #dbe4ee!important}
      [data-testid="stSidebar"] > div:first-child{width:400px!important}
      [data-testid="stSidebarUserContent"]{padding:16px 18px!important}
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.66rem!important}
      [data-testid="stSidebar"] [data-testid="stButton"]>button{
          min-height:38px!important;font-size:12px!important}
      [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p{font-size:12px!important}
      [data-testid="stSidebar"] [data-testid="stCaptionContainer"]{font-size:11px!important}
      [data-testid="stSidebar"] div[data-baseweb="select"]>div{min-height:36px!important}
      .cd-nav-title{color:#627c97;font:750 11px system-ui;letter-spacing:.10em;
          margin:19px 0 11px;border-bottom:1px solid #e4eaf1;padding-bottom:9px}
      .cd-sidebar-brand{color:#1d3c61;font:800 16px system-ui;line-height:1.3;
          letter-spacing:.025em;padding:6px 0 15px}
      .cd-sidebar-brand small{display:block;font-size:10px;letter-spacing:.14em;
          color:#7c90a4;font-weight:650}
      [data-testid="stMainBlockContainer"],.block-container{
          padding:9px 12px 14px!important}
      [data-testid="stSidebar"] [data-testid="stSegmentedControl"]{
          width:100%!important}
      @media(max-width:700px){
        [data-testid="stSidebar"]{width:400px!important;min-width:400px!important}
      }
    </style>
    """, unsafe_allow_html=True)

    result=st.session_state.get("result")
    config=_cfg()
    with st.sidebar:
        st.markdown(
            '<div class="cd-sidebar-brand"><small>RADAR COVERAGE WORKSPACE</small>'
            'COVERAGEDIAGRAMS</div>',unsafe_allow_html=True)

        section=st.segmented_control(
            "Pracovní sekce",
            options=["MAPA","PŘEKÁŽKY","RADAR"],
            default="MAPA",key="ws_section",selection_mode="single",
            width="stretch",label_visibility="collapsed")
        if section is None:
            section="MAPA"
        if section=="MAPA":
            st.markdown('<div class="cd-nav-title">VZHLED MAPY</div>',unsafe_allow_html=True)
            st.segmented_control("Režim",["DAY","NIGHT"],default="DAY",
                                 key="ws_daynight",width="stretch",
                                 label_visibility="collapsed")
            st.markdown('<div class="cd-nav-title">VRSTVY KRYTÍ</div>',unsafe_allow_html=True)
            if result is None:
                st.caption("Po výpočtu zde budeš přepínat jednotlivé letové hladiny.")
            else:
                supported=tuple(core.flight_levels_for(result["config"].radar_mode))
                selected=sorted(set(int(ft) for ft in st.session_state.get("ws_levels",[])
                                    if ft in supported))
                if not selected:
                    selected=list(supported)
                st.toggle("Zobrazit radarové krytí",value=True,key="ws_show_coverage")
                st.segmented_control(
                    "Zobrazení hladin",["Jedna hladina","Porovnání","Cíl"],
                    default="Jedna hladina",key="ws_display_mode",width="stretch",
                    label_visibility="collapsed")
                mode=st.session_state.get("ws_display_mode","Jedna hladina")
                if mode=="Jedna hladina":
                    previous_level=st.session_state.get("ws_map_level")
                    if previous_level not in selected:
                        st.session_state["ws_map_level"]=selected[0]
                    previous_button, level_choice, next_button=st.columns(
                        [0.65,2.7,0.65],gap="small",vertical_alignment="bottom")
                    with previous_button:
                        st.button("◀",key="ws_level_prev",help="Nižší letová hladina",
                                  use_container_width=True,on_click=_step_flight_level,
                                  args=(-1,))
                    with level_choice:
                        st.selectbox("Aktivní letová hladina",selected,
                                     key="ws_map_level",format_func=core.level_label)
                    with next_button:
                        st.button("▶",key="ws_level_next",help="Vyšší letová hladina",
                                  use_container_width=True,on_click=_step_flight_level,
                                  args=(1,))
                    st.caption(f"Zvolená hladina · {selected.index(st.session_state['ws_map_level'])+1}"
                               f" z {len(selected)}")
                elif mode=="Porovnání":
                    current=st.session_state.get("ws_comparison")
                    if current is not None:
                        valid=[ft for ft in current if ft in selected]
                        if valid!=current:
                            st.session_state["ws_comparison"]=valid
                    st.multiselect("Hladiny současně v mapě",selected,
                                   default=selected[:3],key="ws_comparison",
                                   format_func=core.level_label)
                    a,b=st.columns(2,gap="small")
                    with a:
                        st.button("Všechny",key="ws_levels_all",use_container_width=True,
                                  on_click=_select_comparison_levels,args=(True,))
                    with b:
                        st.button("Žádná",key="ws_levels_none",use_container_width=True,
                                  on_click=_select_comparison_levels,args=(False,))
                    count=len(st.session_state.get("ws_comparison",[]))
                    st.caption(f"V mapě je vybráno {count} z {len(selected)} hladin.")
                else:
                    st.caption("Zobrazuje se pokrytí pro cílovou výšku z nastavení radaru.")
                with st.expander("Průhlednost krytí",expanded=False):
                    st.slider("Průhlednost",0.,1.,.42,.05,key="ws_map_opacity",
                              label_visibility="collapsed")
            st.markdown('<div class="cd-nav-title">LETECKÁ MAPA A PROVOZ</div>',unsafe_allow_html=True)
            enabled=st.toggle("OpenAIP · letecká mapa",value=True,key="ws_openaip")
            if enabled:
                from aviation_basemap import configured_key
                if not configured_key():
                    st.caption("OpenAIP vyžaduje OPENAIP_API_KEY v nastavení aplikace.")
            st.toggle("ADS-B LIVE",value=False,key="ws_live_adsb")

        elif section=="RADAR":
            st.markdown('<div class="cd-nav-title">STANOVIŠTĚ RADARU</div>',unsafe_allow_html=True)
            st.caption("Kliknutím do mapy umístíš radar. Po výběru se vrátíš do sekce MAPA.")
            st.markdown(f"**LAT** {config.lat:.6f}° &nbsp; **LON** {config.lon:.6f}°",
                        unsafe_allow_html=True)
            if st.button("⚙ Nastavení radaru",key="ws_command_radar",
                         use_container_width=True):
                radar_dialog()
            st.markdown('<div class="cd-nav-title">VÝPOČET KRYTÍ</div>',unsafe_allow_html=True)
            if st.button("▶ SPOČÍTAT KRYTÍ",type="primary",
                         use_container_width=True,key="ws_calculate_main"):
                _calculate_coverage()
            if result is not None:
                stale=(result.get("obstacles_signature")!=obstacle_signature(
                    st.session_state.get("obstacles",[])) or config!=result["config"])
                st.caption("Výsledek je potřeba přepočítat." if stale
                           else "Výpočet je aktuální.")
            st.markdown('<div class="cd-nav-title">PROJEKT A DATA</div>',unsafe_allow_html=True)
            if st.button("⇩ Export ZIP",key="ws_command_export",use_container_width=True):
                exports_dialog()

        else:  # PŘEKÁŽKY
            st.markdown('<div class="cd-nav-title">ZAKRESLENÍ PŘEKÁŽEK</div>',unsafe_allow_html=True)
            st.caption("Na hlavní mapě použij nástroj polygon. Po dokončení zadáš výšku a název.")
            total_catalog=len(st.session_state.get("ws_imported_catalog",[]))
            st.metric("Výpočetní překážky",len(st.session_state.get("obstacles",[])))
            st.caption(f"Načtené geodatové objekty v editoru: {total_catalog:,} "
                       "(včetně neznámých výšek).")
            if st.button("⬡ Geodata / okolní překážky",key="ws_command_geodata",
                         use_container_width=True):
                layers_dialog()
            if st.button("▧ Upravit / odstranit překážky",key="ws_command_obstacles",
                         use_container_width=True):
                obstacles_dialog()
            st.caption("Změny překážek vyžadují nový výpočet krytí. "
                       "Přejdi do sekce RADAR a klikni na SPOČÍTAT KRYTÍ.")

        # Legacy controls remain available without mixing export tools into obstacles.
        with st.expander("Pokročilé",expanded=False):
            st.toggle("Původní Folium mapa (záloha)",value=False,
                      key="ws_legacy_map",help="Pro kontrolu starého mapového zobrazení.")
            if st.button("Klasické UI",key="ws_legacy",use_container_width=True):
                st.query_params["classic"]="1"
                st.rerun()

    if st.session_state.get("ws_daynight","DAY")=="NIGHT":
        st.markdown("""
        <style>
        [data-testid="stAppViewContainer"]{background:#0b131e!important;color:#dce8f4!important}
        [data-testid="stSidebar"]{background:#101a28!important;border-right-color:#26364b!important}
        [data-testid="stSidebarUserContent"]{background:#101a28!important}
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
        [data-testid="stSidebar"] label{color:#d4e3f0!important}
        [data-testid="stSidebar"] .cd-nav-title{color:#8faac5!important;border-bottom-color:#34455a!important}
        [data-testid="stSidebar"] .cd-sidebar-brand{color:#f0f7ff!important}
        [data-testid="stSidebar"] .cd-sidebar-brand small{color:#8bb1ce!important}
        [data-testid="stSidebar"] [data-testid="stButton"]>button{
          background:#1b2d40!important;color:#e2f0fc!important;border-color:#35516a!important}
        [data-testid="stSidebar"] [data-testid="stButton"]>button[kind="primary"]{
          background:#2760b5!important;color:#fff!important}
        [data-testid="stSidebar"] div[data-baseweb="select"]>div,
        [data-testid="stSidebar"] div[data-baseweb="input"]{
          background:#142336!important;color:#e5eff8!important;border-color:#344d64!important}
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:#a3b6c9!important}
        [data-testid="stSidebar"] [data-testid="stExpander"]{
          background:#162536!important;border-color:#30435a!important}
        [data-testid="stSidebar"] [data-testid="stAlert"]{background:#172638!important}
        </style>
        """,unsafe_allow_html=True)

    # The map is always present and does not change when the sidebar section changes.
    if result is None:
        st.caption(f"RADAR · {config.lat:.6f}°, {config.lon:.6f}° · "
                   f"{len(st.session_state.get('obstacles',[]))} překážek")
    else:
        is_stale=(result.get("obstacles_signature")!=obstacle_signature(
            st.session_state.get("obstacles",[])) or config!=result["config"])
        if is_stale:
            st.warning("Nastavení nebo překážky se změnily. Zobrazené krytí patří k předchozímu výpočtu.")
        else:
            st.caption(f"{result['config'].radar_mode} · "
                       f"{config.lat:.6f}°, {config.lon:.6f}° · "
                       f"{len(st.session_state.get('obstacles',[]))} překážek · KRYTÍ AKTUÁLNÍ")
    if st.session_state.pop("ws_result_notice",None):
        st.success("Krytí vypočteno. Letové hladiny přepínáš v sekci MAPA.")

    if st.session_state.get("ws_legacy_map",False):
        if st.session_state.get("ws_live_adsb",False) and section=="MAPA":
            _live_map_frame()
        else:
            _draw_map_folium()
    else:
        _draw_map()
