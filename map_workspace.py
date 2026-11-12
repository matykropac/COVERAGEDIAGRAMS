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
from position_export import make_layer_features, kml_bytes as position_kml_bytes, kmz_bytes as position_kmz_bytes, geojson_bytes as position_geojson_bytes
from airport_geometry import airport_runways, runway_rows, runway_geometry, par_bearing_for_runway, validate_icao, validate_saved_geometry
from airspace_geometry import fetch_airspaces, validate_saved_airspaces, visible_airspaces, as_geojson, import_geojson
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


@st.cache_data(ttl=86400, show_spinner=False, max_entries=1)
def _public_runways():
    """Download at most once per day; UI may keep old loaded runway geometries."""
    return runway_rows()


@st.cache_data(ttl=3600,show_spinner=False,max_entries=8)
def _cached_airspaces(lat,lon,radius,api_key):
    return fetch_airspaces(lat,lon,radius,api_key)


def _range_controls():
    """Standalone geodesic distance reference, independent of coverage results."""
    st.markdown('<div class="cd-nav-title">RANGE · VZDÁLENOST OD RADARU</div>',
                unsafe_allow_html=True)
    st.toggle("RANGE · ZOBRAZIT KRUŽNICI",value=False,key="ws_range_enabled",
              help="Referenční kružnice má střed na souřadnicích radaru.")
    if st.session_state.get("ws_range_enabled",False):
        radius=st.slider("Poloměr [NM]",min_value=1,max_value=260,
                         value=20,step=1,key="ws_range_nm")
        st.caption(f"{radius} NM = {radius*1.852:.2f} km · geodetická kružnice WGS84")



def _position_nearby_controls():
    st.markdown('<div class="cd-nav-title">OKOLNÍ OBJEKTY · 2 KM</div>',
                unsafe_allow_html=True)
    runways=st.session_state.get("ws_airport_geometry") or []
    radar=_cfg()
    if runways:
        ref=runways[0]["midpoint"]
        description=f"střed RWY letiště {st.session_state.get('ws_airport_code','')}"
    else:
        ref=[radar.lat,radar.lon]
        description="aktuální poloha radaru"
    st.caption(f"Střed hledání: {description} · "
               f"{ref[0]:.6f}°, {ref[1]:.6f}° · OpenStreetMap")
    if st.button("NAČÍST BUDOVY / LESY / STOŽÁRY · 2 KM",
                 use_container_width=True,key="ws_position_osm_2km"):
        try:
            with st.spinner("Načítám objekty OSM do 2 km…"):
                fetched=env.fetch_osm(round(ref[0],5),round(ref[1],5),2.0)
            if not fetched:
                st.warning("V okruhu 2 km nejsou dostupné objekty ve zdroji OSM.")
                return
            # Preserve all previous manual obstacles and user edits for
            # repeated OSM objects. Never invent missing heights.
            previous_environment=st.session_state.get("ws_environment",[])
            key=lambda item:(str(item.get("source","")),str(item.get("source_id","")),
                             str(item.get("kind","")))
            deduplicated={key(item):item for item in previous_environment}
            for item in fetched:
                deduplicated[key(item)]=item
            environment=list(deduplicated.values())
            if len(environment)>env.MAX_ENVIRONMENT_ITEMS:
                raise ValueError("Příliš mnoho OSM objektů; menší oblast nebo GeoJSON import.")
            old_catalog={x["id"]:x for x in st.session_state.get("ws_imported_catalog",[])}
            deleted=set(st.session_state.get("ws_imported_deleted_ids",[]))
            catalog=[x for x in catalog_from_data(
                environment,st.session_state.get("ws_wind_data",[]))
                if x["id"] not in deleted]
            for item in catalog:
                old=old_catalog.get(item["id"])
                if old:
                    item.update(name=old["name"],height_m=old["height_m"],
                                enabled=old["enabled"])
            actual,errors=synchronize(
                st.session_state.get("obstacles",[]),catalog,radar.lat,radar.lon,
                auto_enable=False)
            # Commit together only on success: previous map survives an outage.
            st.session_state["ws_environment"]=environment
            st.session_state["ws_imported_catalog"]=catalog
            st.session_state["obstacles"]=actual
            st.session_state["ws_geodata_site"]=(round(ref[0],5),round(ref[1],5))
            st.session_state["ws_obstacle_revision"]=st.session_state.get("ws_obstacle_revision",0)+1
            st.session_state.pop("ws_snapshot_bytes",None)
            st.session_state.pop("ws_position_export_bytes",None)
            st.success(f"Načteno {len(fetched)} objektů. "
                       f"Zobrazeny v mapě a v editoru překážek; "
                       f"neznámé výšky zůstávají neznámé.")
            if errors:
                st.warning(f"{errors} objektů nelze zařadit do výpočtu bez úpravy.")
        except Exception as exc:
            st.error(f"OSM načítání selhalo; předchozí vrstvy zůstaly: {exc}")
    if st.session_state.get("ws_imported_catalog"):
        st.caption(f"Geodata v editoru: {len(st.session_state['ws_imported_catalog']):,} objektů")
    if st.button("SPRAVOVAT / UPRAVIT OBJEKTY",key="ws_position_edit",
                 use_container_width=True):
        obstacles_dialog()
    if st.button("DALŠÍ ZDROJE GEODAT",key="ws_position_sources",
                 use_container_width=True):
        layers_dialog()


@st.dialog("MAPA / EXPORT VRSTEV",width="large")
def position_layers_export_dialog():
    """Export map layers without requiring an existing computed coverage."""
    st.caption("Vyber vrstvy pro QGIS / Google Earth. Radarový výpočet není potřeba. "
               "Výšky překážek jsou atributy AGL; vrstvy jsou 2D.")
    names=[
        ("runways","RWY · prahy, osy, středy"),
        ("airspaces","CTR / TMA · vzdušné prostory"),
        ("obstacles","Ručně vložené a aktivní překážky"),
        ("environment","Budovy, lesy, stožáry, větrné elektrárny"),
    ]
    cols=st.columns(2,gap="small")
    for i,(key,label) in enumerate(names):
        with cols[i%2]:
            st.checkbox(label,value=True,key="ws_pos_export_"+key)
    format_name=st.segmented_control(
        "Formát",["KMZ","KML","GeoJSON"],default="KMZ",
        key="ws_pos_export_format",width="stretch")
    selected=tuple(bool(st.session_state.get("ws_pos_export_"+key,True))
                   for key,_ in names)
    result=st.session_state.get("result")
    if result is not None:
        st.divider()
        st.markdown("**RADAROVÉ KRYTÍ · VŠECHNY LETOVÉ HLADINY**")
        st.caption("Tento export je jiný než mapová geodata výše: obsahuje jednotlivé "
                   "vypočtené hladiny, cílové krytí, překážky a kružnice 20–260 NM.")
        possible=_available_levels(result["config"].radar_mode)
        levels=st.multiselect("Hladiny krytí pro KML [ft]",
            options=possible,
            default=[x for x in st.session_state.get("ws_levels",[]) if x in possible],
            format_func=core.level_label,key="ws_coverage_kml_levels")
        if st.button("PŘIPRAVIT KML · RADAR + FL",key="ws_coverage_kml_make",
                     use_container_width=True,disabled=not levels):
            try:
                from web_support import export_kml
                st.session_state["ws_coverage_kml_ready"]=(
                    tuple(levels),export_kml(result,levels))
            except Exception as exc:
                st.error(f"Radarový KML export selhal: {exc}")
        prepared=st.session_state.get("ws_coverage_kml_ready")
        if prepared and prepared[0]==tuple(levels):
            st.download_button("STÁHNOUT KML · RADAR + LETOVÉ HLADINY",
                data=prepared[1],file_name="COVERAGEDIAGRAMS_coverage_FL.kml",
                mime="application/vnd.google-earth.kml+xml",
                use_container_width=True,key="ws_coverage_kml_download")
    if st.button("PŘIPRAVIT EXPORT VRSTEV",type="primary",
                 use_container_width=True,key="ws_pos_export_prepare"):
        try:
            cfg=_cfg()
            catalog=st.session_state.get("ws_imported_catalog")
            environment=(catalog if catalog is not None else
                         st.session_state.get("ws_environment",[]))
            features=make_layer_features(
                runways=st.session_state.get("ws_airport_geometry") or [],
                airspaces=visible_airspaces(st.session_state.get("ws_airspaces") or [],
                    st.session_state.get("ws_airspace_ctr",True),
                    st.session_state.get("ws_airspace_tma",True),
                    st.session_state.get("ws_airspace_filter_ft",3000)
                    if st.session_state.get("ws_airspace_altfilter",False) else None),
                obstacles=st.session_state.get("obstacles",[]),
                environment=environment,
                site_lat=cfg.lat,site_lon=cfg.lon,
                include_runways=selected[0],include_airspaces=selected[1],
                include_obstacles=selected[2],include_environment=selected[3])
            if not features:
                raise ValueError("Nejsou dostupné žádné prvky ve zvolených vrstvách.")
            fmt=(format_name or "KMZ").upper()
            pack={"KML":position_kml_bytes,
                  "KMZ":position_kmz_bytes,
                  "GEOJSON":position_geojson_bytes}
            st.session_state["ws_position_export_bytes"]=pack[fmt](features)
            st.session_state["ws_position_export_stamp"]=(selected,fmt)
            st.session_state["ws_position_export_count"]=len(features)
        except Exception as exc:
            st.session_state.pop("ws_position_export_bytes",None)
            st.error(f"Export selhal: {exc}")
    current_stamp=(selected,(format_name or "KMZ").upper())
    if (st.session_state.get("ws_position_export_bytes") and
        st.session_state.get("ws_position_export_stamp")==current_stamp):
        ext=current_stamp[1].lower()
        st.success(f"Připraveno {st.session_state.get('ws_position_export_count',0):,} prvků.")
        st.download_button("STÁHNOUT VRSTVY · "+current_stamp[1],
            data=st.session_state["ws_position_export_bytes"],
            file_name="COVERAGEDIAGRAMS_layers."+ext,
            mime={"KML":"application/vnd.google-earth.kml+xml",
                  "KMZ":"application/vnd.google-earth.kmz",
                  "GEOJSON":"application/geo+json"}[current_stamp[1]],
            use_container_width=True,key="ws_pos_export_download")


def _airport_project_metadata():
    return {
        "airport_icao":st.session_state.get("ws_airport_code",""),
        "airport_runways":st.session_state.get("ws_airport_geometry") or [],
        "airspaces":st.session_state.get("ws_airspaces") or [],
        "airspace_source_time":st.session_state.get("ws_airspace_source_time",""),
        "par_model":_par_model_metadata(),
        "par_level_reference":st.session_state.get("ws_par_level_reference","AGL"),
    }


def _restore_airport_metadata(meta):
    saved=meta.get("source_ui") or {}
    st.session_state["ws_airspaces"]=validate_saved_airspaces(saved.get("airspaces",[]))
    st.session_state["ws_airspace_source_time"]=str(saved.get("airspace_source_time",""))[:100]
    code=saved.get("airport_icao")
    runways=saved.get("airport_runways")
    if code and runways:
        code,runways=validate_saved_geometry(code,runways)
        st.session_state["ws_airport_icao"]=code
        st.session_state["ws_airport_code"]=code
        st.session_state["ws_airport_geometry"]=runways
        st.session_state["ws_runway_index"]=0
        st.session_state["ws_runway_end"]=0
        st.session_state["ws_show_runways"]=True
    else:
        st.session_state.pop("ws_airport_geometry",None)
        st.session_state.pop("ws_airport_code",None)


def _airport_controls():
    st.markdown('<div class="cd-nav-title">LETIŠTĚ / GEOMETRIE RWY</div>',
                unsafe_allow_html=True)
    st.text_input("ICAO letiště",key="ws_airport_icao",placeholder="LKPD",
                  max_chars=4,help="OurAirports: orientační veřejná geometrie, nikoli ověřené AIP souřadnice.")
    if st.button("NAČÍST RWY PODLE ICAO",key="ws_load_runways",
                 use_container_width=True):
        try:
            code=validate_icao(st.session_state.get("ws_airport_icao",""))
            runways=airport_runways(code,_public_runways())
            st.session_state["ws_airport_geometry"]=runways
            st.session_state.pop("ws_snapshot_bytes",None)
            st.session_state["ws_airport_code"]=code
            st.session_state["ws_runway_index"]=0
            st.session_state["ws_runway_end"]=0
            st.session_state["ws_show_runways"]=True
        except Exception as exc:
            st.error(f"Nepodařilo se načíst RWY; poslední geometrie zůstala: {exc}")
    runways=st.session_state.get("ws_airport_geometry") or []
    if not runways:
        st.caption("Zadej ICAO; zobrazím osy, prahy, midpoint a prodloužení RWY.")
        return
    st.caption(f"{st.session_state.get('ws_airport_code','')} · "
               "OurAirports (informativní). Pro přesnou PAR studii ověř AIP AD 2.12.")
    st.selectbox("Runway",range(len(runways)),
                 format_func=lambda i:runways[i]["label"],key="ws_runway_index")
    selected=runways[st.session_state["ws_runway_index"]]
    st.selectbox("Přibližovací směr / práh",options=(0,1),
                 format_func=lambda i:"RWY "+selected["ends"][i]["ident"],
                 key="ws_runway_end")
    st.caption(f"TRUE {selected['heading_deg_true']:.2f}° · "
               f"{selected['length_m']:.0f} m · šířka {selected['width_m']:.0f} m")
    st.toggle("Zobrazit geometrii všech RWY",value=True,key="ws_show_runways")
    if config := st.session_state.get("ws_radar"):
        if config=="PAR-NG" and st.button("NASTAVIT AZIMUT PAR PODLE RWY",
                                         key="ws_align_par",use_container_width=True):
            site=_cfg()
            az=par_bearing_for_runway(selected,st.session_state["ws_runway_end"],
                                       site.lat,site.lon)
            st.session_state["ws_bearing"]=round(az,2)
            st.info(f"Osa PAR nastavena na {az:.2f}° TRUE směrem k přibližovacímu koridoru (5 NM). "
                    "Pokud se stanoviště liší, ověř mechanickou orientaci systému.")


def _ensure_par_level_defaults():
    """Initialize PAR levels only for a new selection, never over CDPROJ."""
    if not st.session_state.get("_par_levels_initialized",False):
        st.session_state["ws_levels"]=list(core.PAR_DEFAULT_LEVELS_FT)
        st.session_state["_par_levels_initialized"]=True
        st.session_state["_par_levels_active"]=True


def _on_radar_level_mode_change():
    """Keep custom PAR selections across switching to PSR/SSR and back."""
    if st.session_state.get("ws_radar")=="PAR-NG":
        st.session_state["ws_levels"]=list(
            st.session_state.get("_par_saved_levels",core.PAR_DEFAULT_LEVELS_FT))
        st.session_state["_par_levels_initialized"]=True
        st.session_state["_par_levels_active"]=True
    else:
        if st.session_state.get("_par_levels_active",False):
            st.session_state["_par_saved_levels"]=list(
                st.session_state.get("ws_levels",[]))
        st.session_state["_par_levels_active"]=False
        st.session_state.pop("_par_levels_message",None)


def _add_par_free_levels(raw_key):
    """Append arbitrary PAR heights without overwriting the 41 defaults."""
    try:
        parsed=core.parse_par_flight_levels(
            st.session_state.get(raw_key,""))
        if not parsed:
            raise ValueError("Zadej alespoň jednu hladinu.")
        _ensure_par_level_defaults()
        values=sorted(set(st.session_state.get("ws_levels",[])).union(parsed))
        if len(values)>core.PAR_CUSTOM_MAX_COUNT:
            raise ValueError(f"Maximálně {core.PAR_CUSTOM_MAX_COUNT} hladin.")
        st.session_state["ws_levels"]=values
        st.session_state["_par_saved_levels"]=list(values)
        st.session_state["_par_levels_epoch"]=st.session_state.get("_par_levels_epoch",0)+1
        st.session_state["_par_levels_message"]=(
            f"Přidáno {len(parsed)} výšek; celkem {len(values)} hladin.")
        st.session_state.pop("_par_levels_error",None)
        st.session_state.pop("ws_coverage_kml_ready",None)
        st.session_state.pop("ws_zip_ready",None)
    except ValueError as exc:
        st.session_state["_par_levels_error"]=str(exc)
        st.session_state.pop("_par_levels_message",None)


def _apply_par_free_levels(raw_key):
    """Streamlit callback runs before widgets are constructed.

    There is no PAR multiselect widget bound to ws_levels: editable input
    directly replaces the whole selection, including the empty selection.
    """
    try:
        raw=st.session_state.get(raw_key,"")
        levels=list(core.parse_par_flight_levels(raw))
        st.session_state["ws_levels"]=levels
        st.session_state["_par_levels_initialized"]=True
        st.session_state["_par_levels_active"]=True
        st.session_state["_par_saved_levels"]=list(levels)
        st.session_state["_par_levels_message"]=(
            f"Uloženo {len(levels)} vlastních výšek." if levels
            else "Výběr hladin je prázdný.")
        st.session_state.pop("_par_levels_error",None)
        st.session_state["_par_levels_epoch"]=st.session_state.get("_par_levels_epoch",0)+1
        # Map selection is reconciled later, before rendering the selector.
        st.session_state.pop("ws_coverage_kml_ready",None)
        st.session_state.pop("ws_zip_ready",None)
    except ValueError as exc:
        st.session_state["_par_levels_error"]=str(exc)
        st.session_state.pop("_par_levels_message",None)


def _par_free_levels_editor(context):
    """PAR defaults 2000..6000 ft / 100 ft plus unrestricted custom values."""
    _ensure_par_level_defaults()
    epoch=st.session_state.get("_par_levels_epoch",0)
    present=_chosen_levels("PAR-NG")
    st.caption(f"Standard: 2 000–6 000 ft po 100 ft · "
               f"{len(present)} hladin vybráno. Jednotlivé hodnoty lze přidat "
               "i mimo tento rozsah.")
    add_key=f"ws_par_add_free_{context}_{epoch}"
    with st.form(f"ws_par_add_form_{context}",clear_on_submit=False,
                 enter_to_submit=False,border=False):
        st.text_input("Přidat další hladiny [ft]",
            placeholder="650, 1750, 6250, 10000",key=add_key,
            help="Lze přidat libovolné celé výšky 1–66 000 ft, "
                 "oddělené čárkou, středníkem nebo mezerou.")
        added=st.form_submit_button("＋ PŘIDAT HLADINY",
            type="primary",use_container_width=True,
            on_click=_add_par_free_levels,args=(add_key,))
    key=f"ws_par_free_{context}_{epoch}"
    with st.expander("UPRAVIT CELÝ SEZNAM / ODEBRAT HLADINY",
                     expanded=False):
        with st.form(f"ws_par_levels_form_{context}",clear_on_submit=False,
                     enter_to_submit=False):
            st.text_area("Všechny vybrané hladiny [ft]",
                value=", ".join(map(str,present)),height=132,
                key=key,placeholder="2000, 2100, 2200, 2300",
                help="Tento seznam lze přepsat, zkrátit nebo úplně vymazat.")
            submitted=st.form_submit_button("POUŽÍT CELÝ SEZNAM",
                use_container_width=True,
                on_click=_apply_par_free_levels,args=(key,))
    if (added or submitted) and not st.session_state.get("_par_levels_error"):
        st.rerun(scope="app")
    if st.session_state.get("_par_levels_error"):
        st.error(st.session_state["_par_levels_error"])
    elif st.session_state.get("_par_levels_message"):
        st.caption(st.session_state["_par_levels_message"])
    st.caption("Nové výšky se přidávají k vybraným. "
               "Úplný seznam můžeš kdykoliv upravit nebo smazat.")


def _available_levels(mode):
    """All selectable levels, including custom PAR altitudes saved in session."""
    preset=tuple(core.flight_levels_for(mode))
    if mode != "PAR-NG":
        return preset
    custom=[int(x) for x in st.session_state.get("ws_levels",[])
            if core.valid_flight_level(mode,x)]
    return tuple(sorted(set(preset).union(custom)))


def _chosen_levels(mode):
    """Single source of truth for map, exports and VIEWER handoff."""
    if mode=="PAR-NG":
        _ensure_par_level_defaults()
    values=st.session_state.get("ws_levels",[3000,10000])
    return sorted(set(int(x) for x in values if core.valid_flight_level(mode,x)))


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


def _par_pattern_metadata(pattern):
    if not isinstance(pattern,core.ParScanPattern):
        return None
    return {name:getattr(pattern,name) for name in (
        "scan_mode","steering_loss_db_per_deg","detection_model",
        "reference_snr_db","pd","pfa","pulses","channel_mode",
        "az_beam_step_deg","el_beam_step_deg",
        "coverage_mode","gas_loss_db_per_km","rain_loss_db_per_km",
        "additional_loss_db","sector_edge_loss_db")}


def _par_model_metadata():
    """Settings are stored alongside the project without changing the polar DEM config."""
    return {
        "scan_mode":st.session_state.get("ws_par_scan_mode","TRACKING"),
        "steering_loss_db_per_deg":float(st.session_state.get("ws_par_scan_loss",0.0)),
        "detection_model":st.session_state.get("ws_par_detection","RELATIVE"),
        "reference_snr_db":float(st.session_state.get("ws_par_snr",16.0)),
        "pd":float(st.session_state.get("ws_par_pd",0.8)),
        "pfa":float(st.session_state.get("ws_par_pfa",1e-6)),
        "pulses":int(st.session_state.get("ws_par_pulses",1)),
        "channel_mode":st.session_state.get("ws_par_channels","BOTH"),
        "az_beam_step_deg":float(st.session_state.get("ws_par_az_beam_step",0.3)),
        "el_beam_step_deg":float(st.session_state.get("ws_par_el_beam_step",0.2)),
        "coverage_mode":st.session_state.get("ws_par_quality","FAST"),
        "gas_loss_db_per_km":float(st.session_state.get("ws_par_gas_loss",0.0)),
        "rain_loss_db_per_km":float(st.session_state.get("ws_par_rain_loss",0.0)),
        "additional_loss_db":float(st.session_state.get("ws_par_extra_loss",0.0)),
        "sector_edge_loss_db":float(st.session_state.get("ws_par_sector_edge_loss",6.0)),
    }


def _restore_par_model_metadata(meta):
    values=(meta.get("source_ui") or {}).get("par_model")
    if values is None:
        values={}
    if not isinstance(values,dict):
        raise ValueError("Neplatný model PAR v projektu.")
    allowed={
        "scan_mode":"ws_par_scan_mode",
        "steering_loss_db_per_deg":"ws_par_scan_loss",
        "detection_model":"ws_par_detection",
        "reference_snr_db":"ws_par_snr",
        "pd":"ws_par_pd",
        "pfa":"ws_par_pfa",
        "pulses":"ws_par_pulses",
        "channel_mode":"ws_par_channels",
        "az_beam_step_deg":"ws_par_az_beam_step",
        "el_beam_step_deg":"ws_par_el_beam_step",
        "coverage_mode":"ws_par_quality",
        "gas_loss_db_per_km":"ws_par_gas_loss",
        "rain_loss_db_per_km":"ws_par_rain_loss",
        "additional_loss_db":"ws_par_extra_loss",
        "sector_edge_loss_db":"ws_par_sector_edge_loss",
    }
    if set(values)-set(allowed):
        raise ValueError("Neznámé parametry PAR v projektu.")
    import dataclasses
    # Old CDPROJ archives specified one supplied grid. Restore AZ choice,
    # never invent BOTH; the updated scan solver may still change recalculated
    # results, so legacy outputs must be compared before customer use.
    if "channel_mode" not in values:
        values["channel_mode"]="AZ"
    pattern=dataclasses.replace(core.builtin_par_pattern(),**values)
    pattern.validate_model()
    # Legacy projects without PAR settings must restore safe defaults, not
    # silently inherit a different project's session state.
    st.session_state.update({widget:getattr(pattern,name)
                             for name,widget in allowed.items()})
    ref=(meta.get("source_ui") or {}).get("par_level_reference","AGL")
    if ref not in ("AMSL","AGL"):
        raise ValueError("Neplatná výšková reference PAR v projektu.")
    st.session_state["ws_par_level_reference"]=ref


def _pattern(config):
    if config.radar_mode == "PAR-NG":
        import dataclasses
        pattern=dataclasses.replace(core.builtin_par_pattern(),**_par_model_metadata())
        pattern.validate_model()
        return pattern
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


def _visual_project_state():
    """Visual settings saved alongside radar matrices in the CDPROJ metadata."""
    return {"mode":st.session_state.get("ws_display_mode","Jedna hladina"),
            "opacity":st.session_state.get("ws_map_opacity",.42),
            "active_level":st.session_state.get("ws_map_level"),
            "viewport":st.session_state.get("ws_viewport"),
            "section":st.session_state.get("ws_section","MAPA")}


def _open_cdproj(data):
    """Restore a saved project through the original validated calculation path."""
    result,meta=load_project(data)
    airport_data=meta.get("source_ui") or {}
    if airport_data.get("airport_icao") and airport_data.get("airport_runways"):
        validate_saved_geometry(airport_data["airport_icao"],airport_data["airport_runways"])
    validate_saved_airspaces(airport_data.get("airspaces",[]))
    _restore_par_model_metadata(meta)
    cfg=result["config"]
    fresh=core.solve(cfg,result["terrain"],result["site_height"],_pattern(cfg))
    apply_obstacles(fresh,meta.get("obstacles",[]))
    fresh.update(source=result.get("source","PROJECT"),
                 completed_at=result.get("completed_at",""),
                 duration_s=result.get("duration_s",0),
                 obstacles_signature=obstacle_signature(meta.get("obstacles",[])))
    _config_state_from_project(fresh["config"])
    _restore_airport_metadata(meta)
    st.session_state["result"]=fresh
    for key in ("ws_previous_result","ws_before_geometry","ws_snapshot_bytes",
                "ws_viewer_handoff","ws_coverage_kml_ready","ws_zip_ready"):
        st.session_state.pop(key,None)
    st.session_state["geometry"]={}
    st.session_state["obstacles"]=meta.get("obstacles",[])
    st.session_state["ws_levels"]=meta.get("levels",[])
    st.session_state["_par_levels_initialized"]=cfg.radar_mode=="PAR-NG"
    st.session_state["_par_levels_active"]=cfg.radar_mode=="PAR-NG"
    if cfg.radar_mode=="PAR-NG":
        st.session_state["_par_saved_levels"]=list(meta.get("levels",[]))
    st.session_state["_par_levels_epoch"]=st.session_state.get("_par_levels_epoch",0)+1
    st.session_state.pop("_par_levels_message",None)
    st.session_state.pop("_par_levels_error",None)
    st.session_state["ws_map_revision"]=st.session_state.get("ws_map_revision",0)+1
    display=meta.get("display") or {}
    # The loader executes in a dialog fragment: stage widget values so they
    # can be assigned BEFORE any parent widgets render on the full rerun.
    if isinstance(display,dict):
        st.session_state["_pending_cdproj_display"]=display
    viewport=display.get("viewport") if isinstance(display,dict) else None
    if not isinstance(viewport,dict) or not all(k in viewport for k in ("lat","lng","zoom")):
        viewport={"lat":fresh["config"].lat,"lng":fresh["config"].lon,"zoom":8}
    st.session_state["ws_viewport"]=viewport
    st.session_state["ws_next_section"]="MAPA"


@st.dialog("OTEVŘÍT PROJEKT · CDPROJ",width="large")
def project_load_dialog():
    st.caption("Načte projekt COVERAGEDIAGRAMS včetně vypočteného krytí, "
               "terénních dat, překážek a nastavení. Není potřeba znovu stahovat DEM.")
    uploaded=st.file_uploader("Soubor projektu (.cdproj)",type=["cdproj"],
                              key="ws_project_upload")
    if st.button("NAČÍST PROJEKT",type="primary",use_container_width=True,
                 key="ws_project_load",disabled=uploaded is None):
        try:
            _open_cdproj(uploaded.getvalue())
            st.rerun()
        except (ValueError,KeyError,TypeError,OSError) as exc:
            st.error(f"Projekt nelze načíst: {exc}")


def _draft_begin():
    """Restore a per-browser autosaved draft before creating Streamlit widgets."""
    from workspace_autosave import new_token,is_valid_token,read_draft
    if st.session_state.get("_workspace_draft_ready"):
        return
    token=st.query_params.get("draft")
    if not is_valid_token(token):
        token=new_token()
        st.query_params["draft"]=token
    st.session_state["_workspace_draft_token"]=token
    try:
        saved=read_draft(token)
        if saved is not None:
            for key,value in saved["fields"].items():
                # A saved CDPROJ opened in this same session should be
                # authoritative. Restore only on an otherwise new session.
                if key not in st.session_state:
                    st.session_state[key]=value
            st.session_state["_workspace_draft_restored_at"]=saved["saved_at"]
    except (OSError,ValueError,TypeError) as exc:
        st.session_state["_workspace_draft_error"]=str(exc)
    st.session_state["_workspace_draft_ready"]=True


def _draft_checkpoint():
    """Atomic checkpoint; called on RADAR dialog reruns and workspace reruns."""
    from workspace_autosave import save_draft
    token=st.session_state.get("_workspace_draft_token")
    if not token:
        return
    try:
        changed=save_draft(token,st.session_state)
        if changed:
            st.session_state["_workspace_draft_last_update"]=(
                datetime.now().strftime("%H:%M:%S"))
        st.session_state.pop("_workspace_draft_error",None)
    except (OSError,ValueError,TypeError) as exc:
        st.session_state["_workspace_draft_error"]=str(exc)


@st.dialog("RADAR / ENGINEERING CONFIGURATION",width="large")
def radar_dialog():
    """Guided engineering setup with original keys and numeric boundaries intact."""
    st.markdown("""
    <style>
    [data-testid="stDialog"] [data-testid="stDialogContent"]{
        background:#101f33!important;color:#dcefff!important}
    [data-testid="stDialog"] [data-testid="stTabs"] [role="tab"]{
        font-size:11px!important;min-width:0!important;white-space:nowrap}
    .cd-radar-summary{background:#173149;border:1px solid #355875;
        border-radius:8px;padding:11px 12px;margin-bottom:11px;min-width:0;
        min-height:92px;overflow-wrap:anywhere}
    .cd-radar-caption{font:750 9px/1.3 system-ui;letter-spacing:.07em;
        color:#79cbed;overflow-wrap:anywhere}
    .cd-radar-value{font:750 clamp(15px,1.7vw,21px)/1.2 system-ui;
        color:#f3f8ff;margin-top:4px;overflow-wrap:anywhere}
    .cd-radar-unit{font:500 10px/1.4 system-ui;color:#a5c8df;
        overflow-wrap:anywhere}
    .cd-radar-guide{border-left:3px solid #63c9ef;padding:6px 11px;
        font:12px/1.5 system-ui;color:#b9d2e3;background:#172a40;
        border-radius:0 6px 6px 0;margin:6px 0 12px}
    </style>
    """,unsafe_allow_html=True)
    _draft_begin()
    st.caption("Čtyři přehledné kroky · všechny původní radarové parametry, "
               "omezení a ukládání do CDPROJ zůstávají zachované.")
    st.caption("◉ AUTO-DRAFT · průběžně ukládám nastavení radaru a výšky. "
               "Koncept se obnoví po návratu přes stejný odkaz.")
    radar=st.session_state.get("ws_radar","RL-2000")
    lat=st.session_state.get("ws_lat",50.034)
    lon=st.session_state.get("ws_lon",15.781)
    agl=st.session_state.get("ws_agl",20.)
    header=st.columns([1.2,1,1],gap="small")
    with header[0]:
        st.markdown('<div class="cd-radar-summary"><div class="cd-radar-caption">RADAR SYSTEM</div>'
                    '<div class="cd-radar-value">'+str(radar)+'</div>'
                    '<div class="cd-radar-unit">Configuration & simulation</div></div>',
                    unsafe_allow_html=True)
    with header[1]:
        st.markdown('<div class="cd-radar-summary"><div class="cd-radar-caption">ANTENNA HEIGHT</div>'
                    '<div class="cd-radar-value">'+f"{float(agl):.1f}"+'</div>'
                    '<div class="cd-radar-unit">metres AGL</div></div>',unsafe_allow_html=True)
    with header[2]:
        st.markdown('<div class="cd-radar-summary"><div class="cd-radar-caption">RADAR SITE</div>'
                    '<div class="cd-radar-value" style="font-size:14px;padding:9px 0">'
                    +f"LAT {float(lat):.4f}°"+'</div><div class="cd-radar-unit">'
                    +f"LON {float(lon):.4f}°"+'</div></div>',unsafe_allow_html=True)

    location_tab,antenna_tab,terrain_tab,flight_tab=st.tabs([
        "01 · STANOVIŠTĚ","02 · ANTÉNA","03 · TERÉN / MODEL","04 · CÍL / FL"
    ])
    with location_tab:
        st.markdown('<div class="cd-radar-guide">Poloha a montážní výška radarové antény. '
                    'Výšky antény jsou vztažené k terénu v místě instalace (AGL).</div>',
                    unsafe_allow_html=True)
        st.selectbox("Radar",["RL-2000","PAR-NG","SSR"],key="ws_radar",
                     on_change=_on_radar_level_mode_change)
        a,b=st.columns(2,gap="small")
        with a:
            st.number_input("Latitude · WGS84",min_value=-80.0,max_value=80.0,
                            value=50.034,format="%.6f",key="ws_lat")
        with b:
            st.number_input("Longitude · WGS84",min_value=-180.0,max_value=180.0,
                            value=15.781,format="%.6f",key="ws_lon")
        st.number_input("Výška antény [m AGL]",min_value=.1,max_value=5000.,
                        value=20.,key="ws_agl")
        st.caption("Změna souřadnic nebo výšky vyžaduje nové vyhodnocení krytí.")

    with antenna_tab:
        st.markdown('<div class="cd-radar-guide">Skutečný relativní elevační řez '
                    'anténního modelu použitého při výpočtu krytí. Pod grafem je '
                    'uveden původ dat a případná omezení kalibrace.</div>',
                    unsafe_allow_html=True)
        mode=st.session_state.get("ws_radar","RL-2000")
        control_a,control_b=st.columns(2,gap="medium")
        with control_a:
            if mode=="RL-2000":
                st.selectbox("Dosah PSR [NM]",list(core.PSR_RANGES_NM),
                             index=2,key="ws_psr_nm")
                st.selectbox("Svazek",["COMBINED","LOW","HIGH"],key="ws_beam")
            if mode=="PAR-NG":
                st.number_input("Azimut osy [°]",0.,359.99,0.,key="ws_bearing")
            if mode=="SSR":
                st.selectbox("SSR anténa",["Generic Gaussian","Measured SSR.txt"],
                             key="ws_ssr_diagram")
        with control_b:
            st.number_input("Min. elevace [°]",-5.,88.,-1.,key="ws_min")
            st.number_input("Max. elevace [°]",-4.,89.,45.,key="ws_max")
            st.number_input("Tilt antény [°]",-15.,15.,-1.,key="ws_tilt")
        if mode=="PAR-NG":
            st.markdown("**VÝPOČETNÍ ANTÉNY PAR-NG**")
            st.radio("Anténa použitá pro výpočet krytí",
                options=["AZ","EL","BOTH"],horizontal=True,
                format_func=lambda mode:{
                    "AZ":"HORIZONTAL · AZ",
                    "EL":"VERTICAL · EL",
                    "BOTH":"OBĚ · AZ + EL",
                }[mode],key="ws_par_channels")
            st.caption("AZ: úzký svazek skenuje zleva doprava (±15°). "
                       "EL: úzký svazek skenuje zdola nahoru (−1 až +14°). "
                       "OBĚ: průnik dosažitelného krytí obou kanálů. "
                       "Zisky ani SNR se nesčítají.")
            az_step_col,el_step_col=st.columns(2,gap="small")
            with az_step_col:
                st.number_input("Krok poloh AZ svazku [°]",min_value=.05,
                    max_value=.9,value=.3,step=.05,format="%.2f",
                    key="ws_par_az_beam_step",
                    help="Simulační krok elektronicky povelovaných směrů; "
                         "skutečný režim sekvence Y8600 zatím není doložen.")
            with el_step_col:
                st.number_input("Krok poloh EL svazku [°]",min_value=.05,
                    max_value=.65,value=.2,step=.05,format="%.2f",
                    key="ws_par_el_beam_step",
                    help="Simulační krok v elevaci; nenahrazuje měření skutečné skenovací sekvence.")
            st.caption("Směry svazků se kvantují do naprogramovaných poloh. "
                       "V každém výpočetním bodě se vyhodnotí odchylka od "
                       "nejbližší polohy, úhlový zisk a steering loss.")

            if st.session_state.get("ws_par_channels","BOTH") in ("EL","BOTH"):
                st.warning("EL anténa používá provizorní úzký "
                           "elektronicky vychylovaný svazek (Gaussian ≤0,65° HPBW), "
                           "nikoli změřenou charakteristiku. Výstup je "
                           "simulace skenování, ne validovaná detekční obálka.")
        # The heavy Plotly antenna heatmaps are only built on explicit request.
        # Streamlit tabs instantiate ALL their contents on each parameter edit:
        # eager plotting here previously caused jitter even in the site tab.
        preview=st.toggle("ZOBRAZIT ANTÉNNÍ DIAGRAMY / AESA NÁHLED",
                          value=False,key="ws_radar_preview_enabled",
                          help="Náročné grafy zůstanou vypnuté během zadávání "
                               "souřadnic a RF parametrů; pro kontrolu je "
                               "kdykoliv zapneš.")
        if preview:
            st.markdown('<div class="cd-panel-title">ANTENNA GAIN / ELEVATION CUT</div>',
                        unsafe_allow_html=True)
            try:
                from antenna_workspace_preview import antenna_figure
                diagram_config=_cfg()
                diagram_pattern=_pattern(diagram_config)
                diagram,source_name,limitations=antenna_figure(
                    diagram_config,diagram_pattern)
                st.plotly_chart(diagram,use_container_width=True,
                                key="ws_radar_antenna_chart",
                                config={"displaylogo":False,"responsive":True})
                st.caption("DATA SOURCE · "+source_name)
                st.caption(limitations)
                if mode=="PAR-NG":
                    from antenna_workspace_preview import par_3d_figure,par_pattern_info
                    detail=par_pattern_info(diagram_pattern)
                    st.markdown("**3D ANTENNA GAIN · 9 GHz SOURCE GRID**")
                    view=st.segmented_control("Pohled diagramu",
                        ["Provozní sektor ±20°","Celá anténa ±180°"],
                        default="Provozní sektor ±20°",
                        key="ws_par_3d_view",width="stretch")
                    fig3d=par_3d_figure(
                        diagram_pattern,near_field=view=="Provozní sektor ±20°")
                    st.plotly_chart(fig3d,use_container_width=True,
                        key="ws_radar_par_3d_heatmap",
                        config={"displaylogo":False,"responsive":True})
                    if diagram_pattern.scan_mode=="TRACKING":
                        from antenna_workspace_preview import par_scanned_coverage_figure
                        st.markdown("**AESA · SKENOVANÁ DOSAHOVÁ OBÁLKA**")
                        st.caption("Výpočet napříč všemi povelovanými polohami "
                                   "svazku, nikoli statický anténní diagram. "
                                   "Barva vyjadřuje maximální *modelový* dosah "
                                   "před započtením terénního horizontu.")
                        scanned=par_scanned_coverage_figure(diagram_pattern)
                        st.plotly_chart(scanned,use_container_width=True,
                            key="ws_radar_par_scan_envelope",
                            config={"displaylogo":False,"responsive":True})
                        st.caption("Základ je 40 km; tento úhlový náhled nezahrnuje "
                                   "skutečný terén ani scénářový útlum závislý na vzdálenosti. "
                                   "Nejde o ověřenou Pd.")

                    a,b,c=st.columns(3,gap="small")
                    a.metric("ELEVACE × AZIMUT",
                        f"{detail['elevation_samples']} × {detail['azimuth_samples']}")
                    b.metric("KROK DIAGRAMU",
                        f"{detail['elevation_step_deg']:g}° / {detail['azimuth_step_deg']:g}°")
                    c.metric("MAX. ZDROJOVÁ HODNOTA",
                        f"{detail['source_peak_db']:.4f} dB")
                    st.caption("SOUBOR: 3Dscan9GHz05deg(2).txt · SHA-256 "
                               +detail["sha256"])
                    st.info("Výpočet používá relativní zisk normalizovaný na 0 dB v "
                            "globálním maximu. Importovaný 3D diagram nemá doložený "
                            "absolutní zisk v dBi, certifikovanou kalibraci, "
                            "model rušení ani atmosférické útlumy.")
                if mode=="RL-2000":
                    st.caption("LOW = vysílací/přijímací svazek · "
                               "HIGH = pouze přijímací svazek. Průběhy jsou "
                               "normalizované, nikoli absolutní zisk dBi.")
            except (ValueError,TypeError,KeyError,OSError) as exc:
                st.warning("Anténní náhled není dostupný: "+str(exc))
            st.caption("Graf je pouze čtecí náhled. RF výpočet stále používá "
                       "původní anténní objekt a jeho interpolaci.")
        if mode=="PAR-NG":
            from par_y8600_spec import (
                AZIMUTH_ANTENNA,ELEVATION_ANTENNA,audit)
            with st.expander("Y8600 · DVĚ ANTÉNY / KONTROLA MODELU",
                             expanded=False):
                cols=st.columns(2,gap="small")
                with cols[0]:
                    st.markdown("**AZIMUTH ANTENNA**")
                    st.caption("Úzký horizontální svazek; HPBW ≤ "
                               f"{AZIMUTH_ANTENNA.beamwidth_limit_deg:.2f}°")
                    st.caption("Vertikální charakteristika: kosekantní.")
                with cols[1]:
                    st.markdown("**ELEVATION ANTENNA**")
                    st.caption("Úzký vertikální svazek; HPBW ≤ "
                               f"{ELEVATION_ANTENNA.beamwidth_limit_deg:.2f}°")
                    st.caption("Horizontální charakteristika: široká.")
                rows=audit(_cfg())
                st.dataframe(rows,hide_index=True,use_container_width=True)
                if any(not row["aligned"] for row in rows):
                    st.warning("Aktuální geometrie není zcela shodná s "
                               "provozními limity Y8600 (elevace −1 až +14°).")
                st.caption("Y8600 potvrzuje dva fyzické RF kanály, ale "
                           "importovaný diagram je jeden datový soubor. "
                           "Bez druhé kalibrované charakteristiky nelze "
                           "zaručit fyzikálně správný společný detekční model.")

    with terrain_tab:
        st.markdown('<div class="cd-radar-guide">Terénní zdroj a numerická mřížka '
                    'přímo určují rozlišení výsledného výpočtu.</div>',
                    unsafe_allow_html=True)
        st.selectbox("Zdroj terénu",["OpenTopography","DEM soubor"],key="ws_source")
        if st.session_state["ws_source"]=="DEM soubor":
            st.file_uploader("GeoTIFF / DTED / HGT",
                             type=["tif","tiff","dt0","dt1","dt2","hgt"],key="ws_dem")
        else:
            st.selectbox("DEM dataset",list(core.DATASETS),key="ws_dataset")
        a,b=st.columns(2,gap="small")
        with a:
            st.select_slider("Radiální krok [m]",options=[25,50,100,250,500,1000,2000],
                             value=500,key="ws_step")
        with b:
            st.select_slider("Azimutální krok [°]",options=[.25,.5,1.,2.,2.5,5.],
                             value=1.,key="ws_azstep")
        st.number_input("k-factor",.5,3.,4/3,format="%.4f",key="ws_k")
        try:
            current=_cfg()
            az,d=core.axes(current)
            samples=len(az)*len(d)
            st.metric("VÝPOČETNÍ SÍŤ",f"{samples:,} vzorků")
            if samples>750000:
                st.warning("Překročen limit 750 000 vzorků. Zvětši krok.")
            else:
                st.progress(min(1.,samples/750000.))
        except Exception:
            st.caption("Výpočetní síť bude zkontrolována při spuštění výpočtu.")

    with flight_tab:
        st.markdown('<div class="cd-radar-guide">Referenční výška cíle a letové '
                    'hladiny pro výsledné mapy. AMSL = nad mořem, AGL = nad terénem.</div>',
                    unsafe_allow_html=True)
        a,b=st.columns(2,gap="small")
        with a:
            st.number_input("Výška cíle [m]",-500.,30000.,1000.,key="ws_target")
        with b:
            st.selectbox("Reference cíle",["AMSL","AGL"],key="ws_reference")
        mode=st.session_state.get("ws_radar","RL-2000")
        if mode=="PAR-NG":
            st.markdown("**LIBOVOLNÉ VÝŠKY · PAR-NG**")
            _par_free_levels_editor("radar")
        else:
            # Preset-based PSR/SSR logic remains unchanged.
            choices=_available_levels(mode)
            if "ws_levels" in st.session_state:
                st.session_state["ws_levels"]=[
                    x for x in st.session_state["ws_levels"]
                    if core.valid_flight_level(mode,x)]
            default=[x for x in (3000,10000) if x in choices]
            st.multiselect("Letové hladiny [ft AMSL]",choices,default=default,
                           format_func=core.level_label,key="ws_levels")
        if st.session_state.get("ws_radar")=="PAR-NG":
            st.markdown("**PAR-NG · ANTÉNA / DETEKCE**")
            st.selectbox("Model 3D antény",["TRACKING","FIXED_3D"],
                         format_func=lambda mode:"AESA beam steering AZ / EL + úhlová ztráta"
                         if mode=="TRACKING" else "Pouze AZ: statický 3D diagram bez skenování",
                         key="ws_par_scan_mode")
            st.number_input("Ztráta skenu [dB/°] · orientační",min_value=0.,max_value=5.,
                            value=0.,step=.05,key="ws_par_scan_loss")
            st.select_slider(
                "Útlum na okraji sektoru ±15° [dB] · simulační předpoklad",
                options=[0.0,1.5,3.0,4.0,6.0,8.0,10.0],
                value=6.0,key="ws_par_sector_edge_loss")
            st.caption("Kvadratický profil: L(α) = Lmax × (|α| / 15°)². "
                       "Výchozí −6 dB, porovnávací −3 dB. Nejde o naměřený "
                       "vyzařovací diagram ani ověřenou RF bilanci.")
            st.markdown("**REŽIM VÝPOČTU · AESA**")
            st.segmented_control("Úroveň detailu",["FAST","ENGINEERING"],
                                 default="FAST",key="ws_par_quality",
                                 width="stretch")
            if st.session_state.get("ws_par_quality","FAST")=="FAST":
                st.caption("FAST · předpočítaná úhlová LUT, stejný fyzikální "
                           "model, rychlé opakované hladiny a změny kanálu.")
            else:
                st.caption("ENGINEERING · přímé vyhodnocení poloh skenu bez LUT. "
                           "Zohledňuje zadané scénářové útlumy na každé "
                           "skutečné šikmé vzdálenosti.")
            with st.expander("RF ZTRÁTY / PROPAGACE · SCÉNÁŘ",expanded=False):
                st.caption("Jednosměrné koeficienty dB/km. Pro radar se "
                           "uplatní obousměrný útlum. Nuly znamenají "
                           "nezadaný útlum, nikoli bezchybnou atmosféru.")
                p,q=st.columns(2,gap="small")
                with p:
                    st.number_input("Atmosférické plyny [dB/km]",
                        min_value=0.,max_value=60.,step=.005,format="%.3f",
                        value=0.,key="ws_par_gas_loss")
                with q:
                    st.number_input("Déšť [dB/km]",
                        min_value=0.,max_value=60.,step=.01,format="%.3f",
                        value=0.,key="ws_par_rain_loss")
                st.number_input("Další ztráta RF systému [dB]",
                    min_value=0.,max_value=60.,step=.5,value=0.,
                    key="ws_par_extra_loss")
                st.caption("Koeficienty nejsou automaticky odvozené z "
                           "ITU-R ani z měření Y8600. Clutter a difrakce "
                           "nejsou součástí tohoto modelu.")
            st.selectbox("Detekční rozpočet",["RELATIVE","ALBERSHEIM"],
                         format_func=lambda mode:"Relativní obálka 40 km"
                         if mode=="RELATIVE" else "Ilustrační SNR / Pd / Pfa",
                         key="ws_par_detection")
            if st.session_state.get("ws_par_detection")=="ALBERSHEIM":
                st.number_input("Referenční SNR na 40 km [dB] · předpoklad",
                                min_value=-20.,max_value=60.,value=16.,step=.5,
                                key="ws_par_snr")
                st.number_input("Požadované Pd",min_value=.01,max_value=.99,
                                value=.8,step=.01,key="ws_par_pd")
                st.selectbox("Požadované Pfa",
                             options=[1e-3,1e-4,1e-5,1e-6,1e-7,1e-8],
                             index=3,key="ws_par_pfa",format_func=lambda n:f"{n:.0e}")
                st.number_input("Počet ne-koherentních pulzů",min_value=1,
                                max_value=1000,value=1,step=1,key="ws_par_pulses")
            if (st.session_state.get("ws_par_scan_mode","TRACKING")=="FIXED_3D"
                    and st.session_state.get("ws_par_channels","BOTH")!="AZ"):
                st.warning("FIXED_3D umí jen statický dostupný diagram. "
                           "Pro elektronický sken EL či OBĚ přepni na TRACKING.")
            st.caption("Parametry PAR skenu a SNR jsou modelové, nikoliv změřená specifikace.")
    st.divider()
    _draft_checkpoint()
    if st.session_state.get("_workspace_draft_error"):
        st.warning("Automatické uložení není dostupné: "
                   +st.session_state["_workspace_draft_error"])
    if st.button("▶ VYPOČÍTAT RADAROVÉ KRYTÍ",type="primary",
                 use_container_width=True,key="ws_calculate"):
        _draft_checkpoint()
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
            # Validate AZ/EL channel availability before expensive DEM download.
            pattern_for_run=_pattern(c)
            if c.radar_mode=="PAR-NG":
                log("PAR kanály: "+pattern_for_run.channel_mode+
                    " · AZ: importovaný relativní vzor · EL: provizorní Y8600 model")
            az,distance=core.axes(c)
            samples=len(az)*len(distance)
            log(f"Radar: {c.radar_mode} · {c.lat:.6f}°, {c.lon:.6f}°")
            log(f"Výpočetní síť: {len(az)} azimutů × {len(distance)} vzdáleností = {samples:,} vzorků")
            if samples>750000:
                raise ValueError("Výpočet přesahuje 750 000 vzorků. Zvětši radiální nebo azimutální krok.")

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
            result=core.solve(c,terrain,ground,pattern_for_run)
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
            st.session_state.pop("ws_previous_result",None)
            st.session_state.pop("ws_before_geometry",None)
            st.session_state.geometry={}
            st.session_state.pop("ws_snapshot_bytes",None)
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


def _recalculate_cached_terrain():
    """Recalculate against the already sampled DEM; no network or DEM download."""
    previous=st.session_state.get("result")
    if previous is None:
        raise ValueError("Nejprve vypočítej nebo načti projekt.")
    requested=_cfg()
    base=previous["config"]
    if requested != base:
        raise ValueError(
            "Parametry radaru se změnily. Pro změnu stanoviště nebo výpočetní "
            "mřížky spusť úplný výpočet; uložený DEM platí pro původní nastavení."
        )
    obstacles=[dict(item) for item in st.session_state.get("obstacles",[])]
    # Transactional: previous result remains untouched on any failure.
    recalculated=core.solve(base,previous["terrain"],previous["site_height"],_pattern(base))
    apply_obstacles(recalculated,obstacles)
    recalculated.update(
        source=previous.get("source","CACHED DEM"),
        completed_at=datetime.now(timezone.utc).isoformat(),
        duration_s=0,
        obstacles_signature=obstacle_signature(obstacles),
    )
    st.session_state["ws_previous_result"]=previous
    st.session_state["ws_before_geometry"]={}
    st.session_state["result"]=recalculated
    st.session_state["geometry"]={}
    st.session_state.pop("ws_snapshot_bytes",None)
    st.session_state["ws_map_revision"]=st.session_state.get("ws_map_revision",0)+1
    st.session_state["ws_result_notice"]="Překážky přepočteny z uloženého terénu."
    st.session_state["ws_next_section"]="MAPA"


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
    opts=_available_levels(result["config"].radar_mode)
    st.caption("Původní exportní nástroje: PDF report 600 DPI, PNG, QuickReport, zákaznické balíčky a datové formáty. Vyber požadované výstupy.")
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
    st.markdown("#### CUSTOMER DELIVERY · LIGHT EDITION")
    st.caption("Profesionální světlé podklady pro zákazníka. Původní ZIP preset výše zůstává beze změny.")
    customer_name=st.text_input(
        "Název projektu / zákazníka",value="Radar Coverage Study",
        key="ws_customer_title")
    customer_options=st.columns(2,gap="small")
    with customer_options[0]:
        st.checkbox("PDF + Coverage Scorecard + metadata",value=True,
                    key="ws_zip_customer_pack")
        st.checkbox("Mapový atlas PNG · 300 DPI · LIGHT",value=False,
                    key="ws_zip_customer_maps")
    with customer_options[1]:
        st.checkbox("Terénní mapa · 300 DPI · LIGHT",value=False,
                    key="ws_zip_customer_terrain")
        st.checkbox("Anténní diagram · 300 DPI · LIGHT",value=False,
                    key="ws_zip_customer_antenna")
    selected.update({
        key:bool(st.session_state.get("ws_zip_"+key))
        for key in ("customer_pack","customer_maps","customer_terrain","customer_antenna")
    })
    if st.button("PŘIPRAVIT ZIP",type="primary",use_container_width=True,key="ws_export_build"):
        try:
            with st.spinner("Připravuji export…"):
                proj=None
                if selected["project"]:
                    proj=save_project(result,levels=st.session_state.get("ws_levels",[]),
                                      obstacles=st.session_state.get("obstacles",[]),
                                      source_ui=_airport_project_metadata(),
                                      display=_visual_project_state())
                html=st.session_state.get("ws_map_html")
                blob=build_selected_zip(
                    result, selected=selected, flight_levels=chosen,
                    index=st.session_state.get("ws_profile_index",0),
                    alpha=st.session_state.get("ws_map_opacity",.42),
                    level_alphas={x:st.session_state.get("ws_map_opacity",.42) for x in chosen},
                    environment_items=[],project_bytes=proj,map_html=html,
                    customer_name=customer_name.strip() or "Radar Coverage Study")
                st.session_state["ws_zip_ready"]=blob
        except Exception as exc:st.error(f"Export selhal: {exc}")
    if st.session_state.get("ws_zip_ready"):
        st.download_button("STÁHNOUT ZIP",st.session_state["ws_zip_ready"],
                           file_name="COVERAGEDIAGRAMS_export.zip",mime="application/zip",
                           use_container_width=True)

    # Independent English customer PDF atlas, not part of the ZIP preset.
    st.divider()
    st.markdown("#### COVERAGE REPORT · PDF · 600 DPI")
    st.caption("English ELDIS report with optional authentic COVERAGE MAPS title page, "
               "terrain model, technical settings and flight-level diagrams.")
    cover_docx = st.file_uploader(
        "ELDIS cover template · COVERAGE MAPS.docx (optional)",
        type=["docx"], key="ws_report_cover_docx",
        help="Upload the original Word document to reproduce its title page artwork in the PDF.")
    report_name=st.text_input("Report / project title",
                              value=customer_name.strip() or "Radar Coverage Study",
                              key="ws_report_title")
    report_levels=st.multiselect(
        "Report flight altitudes [ft AMSL]",opts,
        default=[x for x in st.session_state.get("ws_levels",[]) if x in opts],
        format_func=core.level_label,key="ws_report_levels")
    report_basemap=st.selectbox("Report basemap",
        ("Satelitní · Esri","Esri · Topographic (legacy)",
         "OpenStreetMap","OpenStreetMap + OpenAIP"),key="ws_report_basemap")
    if st.button("GENERATE COVERAGE REPORT · PDF",type="primary",
                 use_container_width=True,key="ws_report_generate"):
        try:
            from coverage_report import CoverageReportOptions, generate_coverage_report_pdf
            report_options=CoverageReportOptions(
                project_name=report_name,
                flight_levels_ft=report_levels,
                basemap=report_basemap,
                dpi=600,
                cover_docx=cover_docx.getvalue() if cover_docx is not None else None)
            with st.spinner("Generating high-resolution 600 DPI report with selected map layers..."):
                st.session_state["ws_report_pdf"]=generate_coverage_report_pdf(
                    result,report_options)
                st.session_state["ws_report_filename"]="Coverage_Report_600dpi.pdf"
        except Exception as exc:
            st.session_state.pop("ws_report_pdf",None)
            st.error(f"Coverage report generation failed: {exc}")
    if st.session_state.get("ws_report_pdf"):
        st.download_button("DOWNLOAD COVERAGE REPORT · PDF",
            data=st.session_state["ws_report_pdf"],
            file_name=st.session_state.get("ws_report_filename","Coverage_Report.pdf"),
            mime="application/pdf",use_container_width=True,
            key="ws_report_download")


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
        levels=_chosen_levels(c.radar_mode)
        if mode=="Cíl":active=[None]
        elif mode=="Porovnání":active=st.session_state.get("ws_comparison",levels[:3])
        elif levels:active=[st.session_state.get("ws_map_level",levels[0])]
        else:active=[]
        for level in active:
            if level is not None and not core.valid_flight_level(c.radar_mode,level):
                continue
            geo=coverage_geojson(result,level,
                reference=st.session_state.get("ws_par_level_reference","AGL")
                if c.radar_mode=="PAR-NG" else "AMSL")
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
        available=_chosen_levels(c.radar_mode)
        # An empty user selection must not secretly re-enable every PAR preset.
        if mode=="Cíl":
            active=[None]
        elif mode=="Porovnání":
            active=[ft for ft in st.session_state.get("ws_comparison",[]) if ft in available]
        elif available:
            wanted=st.session_state.get("ws_map_level",available[0])
            active=[wanted if wanted in available else available[0]]

    coverage=[]
    reference=(st.session_state.get("ws_par_level_reference","AGL")
               if c.radar_mode=="PAR-NG" else "AMSL")
    channel_view=(st.session_state.get("ws_par_diagnostic_layer","VÝSLEDEK")
                  if c.radar_mode=="PAR-NG" else "VÝSLEDEK")
    for level in active:
        if channel_view=="LIMIT":
            from web_support import par_limiting_geojson
            for limiting,color in (("AZ","#5dcdf4"),("EL","#f7c66b")):
                cache_key=(level,reference,"LIMIT",limiting)
                if cache_key not in st.session_state.setdefault("geometry",{}):
                    st.session_state.geometry[cache_key]=par_limiting_geojson(
                        result,level,limiting,reference=reference)
                coverage.append({
                    "geojson":st.session_state.geometry[cache_key],
                    "color":color,
                })
        else:
            cache_key=(level,reference,channel_view)
            if cache_key not in st.session_state.setdefault("geometry",{}):
                if channel_view=="VÝSLEDEK":
                    geo=coverage_geojson(result,level,reference=reference)
                else:
                    from web_support import par_diagnostic_geojson
                    geo=par_diagnostic_geojson(result,level,channel_view,
                                               reference=reference)
                st.session_state.geometry[cache_key]=geo
            colors={"AZ":"#5dcdf4","EL":"#f7c66b","BOTH":"#46e1be"}
            coverage.append({
                "geojson":st.session_state.geometry[cache_key],
                "color":colors[channel_view] if channel_view in colors else (
                    "#247ad3" if level is None else to_hex(core.level_color(level))),
            })
        previous=st.session_state.get("ws_previous_result")
        if (channel_view=="VÝSLEDEK" and previous is not None
                and st.session_state.get("ws_compare_previous",True)):
            if previous["config"]==c:
                # Read-only historic result: retain before/after visibility even
                # when obstacles are removed or the current geometry is cached.
                before_cache=st.session_state.setdefault("ws_before_geometry",{})
                if cache_key not in before_cache:
                    before_cache[cache_key]=coverage_geojson(
                        previous,level,reference=reference)
                coverage.append({"geojson":before_cache[cache_key],"color":"#ed8a2e",
                                 "previous":True})

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
    # WGS84 direct-geodesic circle; exact radial distance in meters.
    range_circle=[]
    if st.session_state.get("ws_range_enabled",False):
        from pyproj import Geod
        radius_m=float(st.session_state.get("ws_range_nm",20))*1852.0
        bearings=np.linspace(0.,360.,181)
        geod=Geod(ellps="WGS84")
        lons,lats,_=geod.fwd(
            np.full(bearings.shape,float(configured.lon)),
            np.full(bearings.shape,float(configured.lat)),
            bearings,np.full(bearings.shape,radius_m))
        range_circle=[[float(lat),float(lon)] for lat,lon in zip(lats,lons)]
    payload={
        "center":[configured.lat,configured.lon],
        "zoom":8 if result else 9,
        "radar":{"lat":configured.lat,"lon":configured.lon,
                 "label":configured.radar_mode+" · RADAR"},
        "basemaps":basemaps,
        "openaip":openaip,
        "theme":st.session_state.get("ws_daynight","NIGHT"),
        "tool":_map_tool(),
        "live":bool(st.session_state.get("ws_live_adsb",False)),
        "coverage":coverage,
        "airportGeometry":runway_geometry(st.session_state.get("ws_airport_geometry") or [])
           if st.session_state.get("ws_show_runways",True) else [],
        "airportCode":st.session_state.get("ws_airport_code",""),
        "airspaces":[],
        "rangeEnabled":bool(st.session_state.get("ws_range_enabled",False)),
        "rangeNm":int(st.session_state.get("ws_range_nm",20)),
        "rangeCircle":range_circle,
        "opacity":alpha,
        "coverageVersion":signature([active,reference,channel_view,alpha,
                                      result.get("completed_at") if result else None,
                                      st.session_state.get("ws_compare_previous",False),
                                      (st.session_state.get("ws_previous_result") or {}).get("completed_at")]),
        "obstacles":obstacle_data,
        "obstaclesVersion":signature(obstacle_data),
        "environment":environment_data,
        "environmentVersion":signature(environment_data),
        "airspacesVersion":"disabled",
        "profile":profile,
    }
    action=show_persistent_map(payload)
    if isinstance(action,dict):
        event_id=str(action.get("id",""))
        if event_id and event_id != st.session_state.get("ws_last_map_action_id"):
            st.session_state["ws_last_map_action_id"]=event_id
            if action.get("type")=="edit_obstacle":
                kind=str(action.get("kind",""))
                identifier=str(action.get("obstacle_id",""))
                valid=(kind=="manual" and identifier.isdigit() and
                       int(identifier)<len(manual_obstacles))
                valid=valid or (kind=="catalog" and any(
                    x["id"]==identifier for x in st.session_state.get("ws_imported_catalog",[])))
                if valid:
                    st.session_state["ws_selected_obstacle"]={
                        "kind":kind,"id":identifier,"token":event_id}
                    obstacles_dialog()
            elif action.get("type")=="validate_los" and payload["tool"]=="Validate":
                try:
                    lat,lon=coordinates_from_map_click({
                        "lat":action["lat"],"lng":action["lon"]})
                    st.session_state["ws_los_clicked"]={"lat":lat,"lon":lon}
                    st.session_state.pop("ws_los_az_index",None)
                    st.session_state.pop("ws_los_range_index",None)
                    st.rerun()
                except (ValueError,TypeError,KeyError) as exc:
                    st.warning("Výběr LOS bodu selhal: "+str(exc))
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


def _render_los_validation(result):
    """Independent point check: no DEM download, no coverage recalculation."""
    st.markdown('<div class="cd-nav-title">LINE OF SIGHT · MATHEMATICAL CHECK</div>',
                unsafe_allow_html=True)
    if result is None:
        st.info("Nejdříve vypočítej radarové krytí nebo otevři CDPROJ s DEM.")
        return
    from los_validation import verify_radial_point
    from pyproj import Geod
    c=result["config"]
    az_values=np.asarray(result["az"],dtype=float)
    d_values=np.asarray(result["distance"],dtype=float)
    clicked=st.session_state.get("ws_los_clicked")
    st.caption("Klikni do mapy pro výběr cílového bodu. Výpočet nezávisle "
               "kontroluje geometrii vůči hlavnímu výpočtu.")
    if clicked:
        az_raw,_,length=Geod(ellps="WGS84").inv(
            c.lon,c.lat,float(clicked["lon"]),float(clicked["lat"]))
        az=az_raw%360
        near,inside=core.azimuth_indices(az_values,c,az)
        if not inside or length>d_values[-1] or length<d_values[0]/2:
            st.warning("Vybraný bod je mimo výpočetní sektor/dosah.")
            return
        azi=int(near)
        ri=int(np.argmin(np.abs(d_values-length)))
        st.caption(f"Vybraný bod: {clicked['lat']:.6f}°, {clicked['lon']:.6f}° "
                   f"· {length/1000:.2f} km · AZ {az:.2f}°")
    else:
        azi=int(np.argmin(np.abs(az_values-c.bearing_deg))) if c.radar_mode=="PAR-NG" else 0
        ri=min(len(d_values)-1,max(0,int(len(d_values)*.5)))
        st.caption("Zatím žádný bod z mapy: kontroluji střed sektoru na polovině dosahu.")

    ref_options=("AMSL","AGL")
    selected_ref=st.selectbox("Výšková reference",ref_options,
        index=0,key="ws_los_reference")
    levels=_chosen_levels(c.radar_mode)
    selected_level=st.selectbox("Cílová hladina [ft]",
        levels if levels else [2000],key="ws_los_flight_level")
    height_m=float(selected_level)*core.FT_TO_M
    # Slider/index controls let the engineer test adjacent samples without
    # forcing another map click.
    col_a,col_b=st.columns(2,gap="small")
    with col_a:
        azi=st.number_input("Azimut · index",min_value=0,
                            max_value=len(az_values)-1,value=azi,
                            step=1,key="ws_los_az_index")
    with col_b:
        ri=st.number_input("Vzdálenost · index",min_value=0,
                           max_value=len(d_values)-1,value=ri,
                           step=1,key="ws_los_range_index")
    try:
        check=verify_radial_point(result,int(azi),int(ri),height_m,
                                  reference=selected_ref)
    except (ValueError,IndexError,TypeError,KeyError) as exc:
        st.error("LOS validátor: "+str(exc))
        return
    if check["status"]=="UNKNOWN":
        st.warning("NEDOSTATEČNÁ DEM DATA · "+check["reason"])
        return
    if check["status"]=="OBSTACLES_NOT_CHECKED":
        st.warning("LOS DEM · samostatná kontrola terénu. V projektu jsou "
                   "také ručně vložené překážky; ty tato nezávislá DEM "
                   "kontrola neobsahuje. Rozdíl oproti hlavnímu krytí "
                   "proto automaticky neznamená matematickou chybu.")
    elif check["status"]=="MATCH":
        st.success("MATHEMATICAL LOS · MATCH s hlavním geometrickým modelem")
    else:
        st.error("MATHEMATICAL LOS · MISMATCH! Výpočet vyžaduje kontrolu.")
    first,second=st.columns(2,gap="small")
    first.metric("MIN. REZERVA LOS",
                 f"{check['minimum_clearance_m']:+.2f} m")
    second.metric("KRITICKÝ BOD",
                  f"{check['limiting_distance_m']/1000:.2f} km")
    geometric=check["independent_geometry"]
    radio=check["final_coverage"]
    if np.isfinite(radio):
        if geometric and radio<.5:
            st.info("Geometrická LOS vyhovuje, ale výsledné krytí ne: "
                    "pravděpodobná RF/anténní podmínka, nikoliv chyba LOS.")
        elif not geometric and radio>=.5:
            st.error("POZOR: Model hlásí krytí bez geometrické LOS! "
                     "Zkontroluj vstupy, překážky a výpočet.")
    st.caption(f"AZ {check['azimuth_deg']:.3f}° · "
               f"EL {check['elevation_deg']:.3f}° · "
               f"vzdálenost {check['distance_m'][-1]/1000:.2f} km · "
               f"k={c.k:.3f}. Kontrola používá stejné DEM vzorky, "
               "ale nezávislou geometrii tětivy.")
    try:
        import plotly.graph_objects as go
        x=check["distance_m"]/1000
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=x,y=check["terrain_m"],
            name="DEM · AMSL",mode="lines",fill="tozeroy",
            line=dict(color="#9abd87",width=1.6)))
        fig.add_trace(go.Scatter(x=x,y=check["ray_m"],
            name="Radar → cíl · LOS",mode="lines",
            line=dict(color="#5dcdf4",width=2.2)))
        fig.add_vline(x=check["limiting_distance_m"]/1000,
                      line_dash="dot",line_color="#f7c66b")
        fig.update_layout(template="plotly_dark",height=280,
            paper_bgcolor="#10243b",plot_bgcolor="#10243b",
            margin=dict(l=3,r=5,t=8,b=32),
            legend=dict(orientation="h",y=1.13,font=dict(size=9)),
            xaxis_title="Vzdálenost [km]",yaxis_title="Výška [m AMSL]",
            font=dict(size=10,color="#d4e8f5"))
        st.plotly_chart(fig,use_container_width=True,
                        key="ws_los_validation_profile",
                        config={"displaylogo":False,"responsive":True})
        import io,csv
        output=io.StringIO()
        writer=csv.writer(output)
        writer.writerow(["range_m","dem_amsl_m","los_amsl_m","clearance_m"])
        writer.writerows(zip(check["distance_m"],check["terrain_m"],
                             check["ray_m"],check["clearance_m"]))
        st.download_button("⇩ PROFIL LOS · CSV",data=output.getvalue(),
            file_name="COVERAGEDIAGRAMS_LOS_check.csv",mime="text/csv",
            key="ws_los_profile_csv",use_container_width=True)
    except (ImportError,ValueError,TypeError) as exc:
        st.warning("Graf LOS nelze zobrazit: "+str(exc))
    st.caption("VALIDACE 01 · Nezávislá geometrie na stejné vzorkované DEM "
               "síti. Ruční překážky se kontrolují pouze v hlavním enginu. "
               "Nepotvrzuje měřený Pd ani překážky mezi vzorky terénu.")


def _map_tool():
    """Map editing follows the active workspace section automatically."""
    return {
        "MAPA": "Prohlížení",
        "RADAR": "Radar",
        "VALIDACE": "Validate",
        "POZICE": "Prohlížení",
        "PŘEKÁŽKY": "Polygon",
    }.get(st.session_state.get("ws_section","MAPA"),"Prohlížení")


def _restore_sidebar_preferences():
    """Keep options while switching conditional sidebar sections.

    Streamlit removes widget keys when widgets aren't rendered; copy their
    values to independent session-state keys before leaving the MAPA section.
    """
    keys=("ws_show_coverage","ws_display_mode","ws_map_level",
          "ws_comparison","ws_map_opacity","ws_openaip",
          "ws_live_adsb","ws_show_wind")
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
    allowed=_available_levels(result["config"].radar_mode)
    levels=_chosen_levels(result["config"].radar_mode)
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
    levels=_chosen_levels(result["config"].radar_mode)
    st.session_state["ws_comparison"]=levels if select_all else []


def render_workspace():
    """Persistent ATM workstation map with contextual engineering tools."""
    _draft_begin()
    # The most recently submitted Streamlit values are already available in
    # session_state at script start. Persist before conditional widgets vanish.
    _draft_checkpoint()
    pending=st.session_state.pop("_pending_cdproj_display",None)
    if isinstance(pending,dict):
        for field,widget in (("opacity","ws_map_opacity"),
                             ("mode","ws_display_mode"),
                             ("active_level","ws_map_level")):
            value=pending.get(field)
            if value is not None:
                st.session_state[widget]=value
                st.session_state["_persist_"+widget]=value
    previous=st.session_state.get("result")
    if previous is not None and "ws_radar" not in st.session_state:
        _config_state_from_project(previous["config"])
        st.session_state["ws_levels"]=list(st.session_state.get("levels",[3000,10000]))

    _restore_sidebar_preferences()
    st.session_state["ws_daynight"]="NIGHT"  # Fixed workstation palette.

    next_section=st.session_state.pop("ws_next_section",None)
    if next_section in ("MAPA","RADAR","PŘEKÁŽKY","POZICE","TERÉN","EXPORT","VALIDACE"):
        st.session_state["ws_section"]=next_section

    from workspace_theme import COMMON_CSS
    # Palette and logo are shared with the VIEWER; engineering controls stay intact.
    st.markdown(STYLES,unsafe_allow_html=True)
    st.markdown(COMMON_CSS,unsafe_allow_html=True)
    result=st.session_state.get("result")
    st.markdown("""<style>
    [data-testid="stSidebar"]{width:476px!important;min-width:476px!important;
      background:#10243b!important;border-right:1px solid #35506c!important}
    [data-testid="stSidebar"]>div:first-child{width:476px!important}
    [data-testid="stSidebarUserContent"]{padding:12px 10px!important;background:#10243b!important}
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.36rem!important}
    [data-testid="stSidebar"] [data-testid="stButton"]>button{
       min-height:35px!important;font-size:11px!important}
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"]{font-size:10px!important}
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p{font-size:11px!important}
    [data-testid="stSidebar"] div[data-baseweb="select"]>div{min-height:32px!important}
    [data-testid="stSidebar"] .cd-nav-title{font:750 10px system-ui;letter-spacing:.11em;
       color:#91cce8!important;margin:13px 0 7px;border-bottom:1px solid #36516c;padding-bottom:6px}
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
    [data-testid="stSidebar"] label{color:#c2d8ea!important}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]{gap:.35rem!important}
    [data-testid="stSidebar"] [data-testid="stExpander"]{background:#142c45!important}
    /* Tool rail: one button per section; all states share the dark palette. */
    [data-testid="stSidebar"] .st-key-cd_nav_rail [data-testid="stVerticalBlock"]{
        gap:6px!important}
    [data-testid="stSidebar"] .st-key-cd_nav_rail [data-testid="stButton"]>button,
    [data-testid="stSidebar"] .st-key-cd_nav_rail [data-testid="stButton"] button{
        width:100%!important;min-height:42px!important;height:42px!important;
        padding:0 5px!important;display:flex!important;justify-content:center!important;
        align-items:center!important;gap:5px!important;text-align:center!important;
        font:700 10px/1.2 system-ui!important;white-space:nowrap!important;
        background:#182d44!important;color:#bed8eb!important;
        border:1px solid #34526c!important;border-radius:8px!important;
        box-shadow:none!important;overflow:hidden!important}
    [data-testid="stSidebar"] .st-key-cd_nav_rail [data-testid="stButton"]>button[kind="primary"],
    [data-testid="stSidebar"] .st-key-cd_nav_rail [data-testid="stButton"] button[data-testid="stBaseButton-primary"]{
        background:#174b71!important;color:#ebfaff!important;
        border-color:#5bc7f0!important;box-shadow:inset 3px 0 #63c9ef!important}
    [data-testid="stSidebar"] .st-key-cd_nav_rail [data-testid="stButton"]>button:hover{
        background:#244762!important;color:white!important;border-color:#68bfe5!important}
    .cd-viewer-rail-link{display:flex;flex-direction:row;align-items:center;
        justify-content:center;text-align:center;text-decoration:none!important;
        width:100%;box-sizing:border-box;height:44px;
        color:#fff!important;border:1px solid #f17c86;border-radius:8px;
        background:#a92e43;padding:0 5px;margin-top:7px;gap:6px;min-width:0}
    .cd-viewer-rail-link:hover{background:#ce3b52;color:#fff!important}
    .cd-viewer-rail-glyph{font:800 16px/1 system-ui}
    .cd-viewer-rail-label{font:750 10px/1.2 system-ui;white-space:nowrap}
    @media(max-width:700px){[data-testid="stSidebar"]{width:100vw!important;min-width:0!important}
      [data-testid="stSidebar"]>div:first-child{width:100%!important}}
    </style>""",unsafe_allow_html=True)

    result=st.session_state.get("result")
    config=_cfg()
    if st.session_state.get("_workspace_draft_restored_at"):
        st.caption("◉ AUTO-DRAFT · rozpracované nastavení obnoveno "
                   "z posledního uložení. Vypočtený DEM/krytí je nutné "
                   "načíst samostatně z CDPROJ.")
        st.session_state.pop("_workspace_draft_restored_at",None)
    if st.session_state.get("_workspace_draft_error"):
        st.warning("Pracovní koncept nelze ukládat: "
                   +st.session_state["_workspace_draft_error"])
    with st.sidebar:
        rail, gutter, panel = st.columns([1.85,.42,4.65],gap="small")
        with rail:
            # A single native button contains both symbol and name. No
            # independent labels, so Streamlit vertical spacing cannot overlap.
            with st.container(key="cd_nav_rail"):
                for name,symbol,label,tip in (
                    ("MAPA","▧","MAPA","Mapa a krytí"),
                    ("RADAR","◉","RADAR","Radar / výpočet"),
                    ("VALIDACE","✓","TEST","Matematická kontrola LOS"),
                    ("TERÉN","△","TERÉN","Terén / DEM"),
                    ("PŘEKÁŽKY","▤","VRSTVY","Vrstvy a překážky"),
                    ("POZICE","✈","AIP","Aviation / ICAO"),
                    ("EXPORT","⇩","EXPORT","Export Studio")):
                    active=st.session_state.get("ws_section","MAPA")==name
                    if st.button(f"{symbol}  {label}",key="cd_rail_"+name,
                                 help=tip,use_container_width=True,
                                 type="primary" if active else "secondary"):
                        st.session_state["ws_section"]=name
                        st.rerun()
                st.markdown(
                    '<a class="cd-viewer-rail-link" href="?viewer=1" target="_blank" '
                    'rel="noopener noreferrer" title="Otevřít samostatný VIEWER">'
                    '<span class="cd-viewer-rail-glyph">◈</span>'
                    '<span class="cd-viewer-rail-label">VIEWER</span></a>',
                    unsafe_allow_html=True)
        with gutter:
            st.empty()
        with panel:
            st.markdown('<div class="cd-panel-title">'+
                {"MAPA":"MAPA / ANALÝZA","RADAR":"RADAR / ENGINE",
                 "VALIDACE":"VALIDACE / LOS",
                 "TERÉN":"TERÉN / 3D","PŘEKÁŽKY":"VRSTVY / OBSTACLES",
                 "POZICE":"AVIATION / GEODATA","EXPORT":"EXPORT STUDIO"}.get(
                    st.session_state.get("ws_section","MAPA"),"MAPA")+
                '</div>',unsafe_allow_html=True)
            section=st.session_state.get("ws_section","MAPA")
            if section=="MAPA":
                st.markdown('<div class="cd-nav-title">MAPOVÉ PODKLADY A VRSTVY</div>',
                            unsafe_allow_html=True)
                st.markdown('<div class="cd-nav-title">VRSTVY KRYTÍ</div>',unsafe_allow_html=True)
                if result is None:
                    st.caption("Po výpočtu zde budeš přepínat jednotlivé letové hladiny.")
                else:
                    supported=_available_levels(result["config"].radar_mode)
                    selected=sorted(set(int(ft) for ft in st.session_state.get("ws_levels",[])
                                        if ft in supported))
                    if result["config"].radar_mode=="PAR-NG":
                        with st.expander("UPRAVIT VLASTNÍ VÝŠKY PAR",expanded=False):
                            _par_free_levels_editor("map")
                        # Form callbacks may have updated selection before this render.
                        selected=_chosen_levels("PAR-NG")
                        st.radio("Výška PAR nad terénem / mořem",("AGL","AMSL"),
                                 horizontal=True,key="ws_par_level_reference",
                                 help="AGL = nad místním terénem. AMSL = nad hladinou moře.")
                        st.selectbox("PAR · VRSTVA KRYTÍ",
                            ["VÝSLEDEK","AZ","EL","BOTH","LIMIT"],
                            format_func=lambda value:{
                                "VÝSLEDEK":"Nastavená anténa",
                                "AZ":"AZ · horizontální sken",
                                "EL":"EL · vertikální sken",
                                "BOTH":"AZ + EL · společná oblast",
                                "LIMIT":"LIMITING · omezující kanál",
                            }[value],key="ws_par_diagnostic_layer",
                            help="Přepnutí nevyžaduje nové stažení DEM. "
                                 "Vrstvy používají stejnou fyziku, ale "
                                 "oddělené kanálové podmínky.")
                        if st.session_state.get("ws_par_diagnostic_layer")=="LIMIT":
                            st.caption("LIMITING CHANNEL · AZ = cyan | EL = žlutá. "
                                       "Zobrazuje pouze společně pokryté oblasti, "
                                       "kde jeden z kanálů omezuje rezervu.")

                    st.toggle("Zobrazit radarové krytí",value=True,key="ws_show_coverage")
                    st.segmented_control(
                        "Zobrazení hladin",["Jedna hladina","Porovnání","Cíl"],
                        default="Jedna hladina",key="ws_display_mode",width="stretch",
                        label_visibility="collapsed")
                    mode=st.session_state.get("ws_display_mode","Jedna hladina")
                    if mode=="Jedna hladina":
                        if not selected:
                            st.info("Nejsou vybrány žádné hladiny. Přidej je v RADAR → Nastavení.")
                        else:
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
                                st.selectbox("Aktivní výška [ft]",selected,
                                             key="ws_map_level",format_func=lambda ft:
                                             f"{ft:,} ft {st.session_state.get('ws_par_level_reference','AGL') if result['config'].radar_mode=='PAR-NG' else 'AMSL'}")
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
                    if st.session_state.get("ws_previous_result") is not None:
                        st.toggle("BEFORE / AFTER · původní krytí přerušovaně",
                                  value=True,key="ws_compare_previous")
                    with st.expander("Průhlednost krytí",expanded=False):
                        st.slider("Průhlednost",0.,1.,.42,.05,key="ws_map_opacity",
                                  label_visibility="collapsed")
                st.markdown('<div class="cd-nav-title">LETECKÁ MAPA A PROVOZ</div>',unsafe_allow_html=True)
                from aviation_basemap import configured_key,test_tiles_connection
                key_available=bool(configured_key())
                enabled=st.toggle("OpenAIP · letecká mapa",value=True,key="ws_openaip")
                if enabled and not key_available:
                    st.warning("AIP není připojena: chybí OPENAIP_API_KEY nebo "
                               "OPENAIP_DATA_API_KEY v nastavení Streamlitu.")
                if st.button("OVĚŘIT OPENAIP · API / DLAŽDICE",
                             key="ws_aip_test",use_container_width=True):
                    with st.spinner("Kontroluji odpověď mapového serveru…"):
                        st.session_state["ws_aip_test_result"]=test_tiles_connection()
                diag=st.session_state.get("ws_aip_test_result")
                if diag is not None:
                    ok,message=diag
                    if ok:
                        st.success(message)
                    else:
                        st.error(message)
                st.caption("Test ověřuje skutečnou odpověď serveru, nikoliv jen "
                           "přítomnost API klíče. Klíč se nevypisuje.")
                st.toggle("ADS-B LIVE",value=False,key="ws_live_adsb")
                st.markdown('<div class="cd-nav-title">EXPORTNÍ CENTRUM</div>',
                            unsafe_allow_html=True)
                if result is not None:
                    st.caption("Původní výstupy: PDF report 600 DPI, PNG po hladinách, "
                               "QuickReport, zákaznický ZIP, GeoTIFF a další.")
                    if st.button("⇩ PDF 600 DPI / PNG / QUICKREPORT / ZIP",
                                 key="ws_command_export",type="primary",
                                 use_container_width=True):
                        exports_dialog()
                else:
                    st.caption("PDF report a PNG radarového krytí vyžadují vypočtená data. "
                               "Samostatné geodatové vrstvy můžeš exportovat ihned.")
                if st.button("⇩ KML / KMZ / GEOJSON · MAPOVÉ VRSTVY",
                             key="ws_map_export_layers",use_container_width=True,
                             help="Vrstvy RWY, CTR/TMA, překážek a okolních geodat bez výpočtu."):
                    position_layers_export_dialog()

            elif section=="TERÉN":
                st.markdown('<div class="cd-nav-title">DIGITÁLNÍ MODEL TERÉNU</div>',
                            unsafe_allow_html=True)
                st.caption("Terén je společný pro radarový výpočet a 3D vizualizaci.")
                if st.button("⚙ ZDROJ DEM / OPENTOPOGRAPHY",
                             key="ws_terrain_configure",use_container_width=True):
                    radar_dialog()
                st.caption("3D hypsometrie a prostorové zobrazení se otevírá ve VIEWERU.")
                if result is not None:
                    terrain_values=np.asarray(result["terrain"],dtype=float)
                    finite=terrain_values[np.isfinite(terrain_values)]
                    if finite.size:
                        st.metric("Min / max terén [m AMSL]",
                                  f"{np.min(finite):.0f} / {np.max(finite):.0f}")
                        st.caption(f"{finite.size:,} platných výškových vzorků")
                    st.caption("Klikni nahoře na VIEWER S VÝSLEDKEM pro převzetí DEM.")
                else:
                    st.info("V sekci RADAR nastav stanoviště a zdroj terénu.")
            elif section=="EXPORT":
                st.markdown('<div class="cd-nav-title">ZÁKAZNICKÉ VÝSTUPY</div>',
                            unsafe_allow_html=True)
                if result is not None:
                    if st.button("⇩ PDF / PNG 600 DPI / ZIP",key="ws_export_studio",
                                 type="primary",use_container_width=True):
                        exports_dialog()
                    st.caption("Letové hladiny, zákaznické PDF a původní ZIP presety.")
                else:
                    st.caption("PDF krytí vyžaduje předchozí výpočet.")
                if st.button("⇩ KML / KMZ / GEOJSON",key="ws_export_map_layers",
                             use_container_width=True):
                    position_layers_export_dialog()
                if result is not None and result["config"].radar_mode=="PAR-NG":
                    with st.expander("PAR · AZ / EL / OBĚ / LIMITING CHANNEL",
                                     expanded=False):
                        levels=_chosen_levels("PAR-NG")
                        if levels:
                            level=st.selectbox("Diagnostická hladina [ft]",
                                levels,key="ws_par_diagnostic_export_level")
                            reference=st.session_state.get("ws_par_level_reference","AMSL")
                            if st.button("PŘIPRAVIT DIAGNOSTICKÝ ZIP",
                                         key="ws_par_diag_prepare",
                                         use_container_width=True):
                                try:
                                    from par_diagnostics_export import make_diagnostics_zip
                                    blob=make_diagnostics_zip(result,int(level),
                                                             reference=reference)
                                    st.session_state["ws_par_diag_zip"]={
                                        "key":(result.get("completed_at"),int(level),reference),
                                        "data":blob}
                                except Exception as exc:
                                    st.error(f"Nelze připravit PAR diagnostiku: {exc}")
                            ready=st.session_state.get("ws_par_diag_zip")
                            if ready and ready["key"]==(result.get("completed_at"),
                                                         int(level),reference):
                                st.download_button("⇩ STÁHNOUT PAR DIAGNOSTIKU",
                                    data=ready["data"],
                                    file_name=f"PAR_AESA_{level}ft_{reference}.zip",
                                    mime="application/zip",use_container_width=True,
                                    key="ws_par_diag_download")
                            st.caption("AZ, EL a společné GeoJSON; regiony limitující "
                                       "antény AZ/EL; rastry rezerv kanálů "
                                       "v NPZ a popis předpokladů.")
                        else:
                            st.info("Vyber výšky PAR v RADAR → CÍL / FL.")
                st.caption("Mapové vrstvy lze exportovat i bez radarového výpočtu.")
                with st.expander("ZÁLOHA ROZPRACOVANÝCH PARAMETRŮ",expanded=False):
                    from workspace_autosave import export_draft,import_draft
                    st.caption("Automatický draft se průběžně ukládá na server. "
                               "Tato malá záloha umožní obnovu i po vymazání "
                               "serverové cache nebo novém nasazení aplikace.")
                    st.download_button("⇩ STÁHNOUT NASTAVENÍ · JSON",
                        data=export_draft(st.session_state),
                        file_name="COVERAGEDIAGRAMS_radar_draft.json",
                        mime="application/json",key="ws_draft_export",
                        use_container_width=True)
                    draft_upload=st.file_uploader(
                        "Obnovit rozpracované parametry",
                        type=["json"],key="ws_draft_import")
                    if draft_upload is not None and st.button(
                            "OBNOVIT NASTAVENÍ",key="ws_draft_import_apply",
                            use_container_width=True):
                        try:
                            values=import_draft(draft_upload.getvalue())
                            st.session_state.update(values)
                            st.session_state["_par_levels_epoch"]=(
                                st.session_state.get("_par_levels_epoch",0)+1)
                            _draft_checkpoint()
                            st.session_state["ws_draft_restore_notice"]=(
                                f"Obnoveno {len(values)} nastavení ze zálohy.")
                            st.rerun()
                        except (ValueError,TypeError,OSError) as exc:
                            st.error("Zálohu nelze načíst: "+str(exc))
                    if st.session_state.get("ws_draft_restore_notice"):
                        st.success(st.session_state.pop("ws_draft_restore_notice"))
                st.markdown('<div class="cd-nav-title">SPRÁVA PROJEKTU / CDPROJ</div>',
                            unsafe_allow_html=True)
                first_btn,second_btn=st.columns(2,gap="small")
                with first_btn:
                    if st.button("OPEN · CDPROJ",key="ws_export_project_load",
                                 use_container_width=True):
                        project_load_dialog()
                with second_btn:
                    if result is not None and st.button("SAVE · CDPROJ",
                                                         key="ws_export_save_project",
                                                         use_container_width=True):
                        try:
                            st.session_state["ws_top_project_bytes"]=save_project(
                                result,levels=st.session_state.get("ws_levels",[]),
                                obstacles=st.session_state.get("obstacles",[]),
                                source_ui=_airport_project_metadata(),
                                display=_visual_project_state())
                        except Exception as exc:
                            st.error(f"Projekt nelze připravit: {exc}")
                if st.session_state.get("ws_top_project_bytes"):
                    st.download_button("⇩ STÁHNOUT CDPROJ",
                        data=st.session_state["ws_top_project_bytes"],
                        file_name="COVERAGEDIAGRAMS_project.cdproj",
                        mime="application/octet-stream",use_container_width=True,
                        key="ws_export_cdproj_download")

                st.markdown('<div class="cd-nav-title">VIEWER / PŘENOS VÝSLEDKU</div>',
                                unsafe_allow_html=True)
                if result is not None:
                    if st.button("↗ VIEWER S VÝSLEDKEM",
                                 key="ws_export_viewer_snapshot",use_container_width=True,
                                 help="Přenese vypočtené hladiny a DEM do nového okna."):
                        try:
                            from viewer_bridge import publish
                            chosen=st.session_state.get("ws_levels",[])
                            allowed=set(_available_levels(result["config"].radar_mode))
                            chosen=[int(x) for x in chosen if int(x) in allowed]
                            token=publish(result,chosen,st.session_state.get("obstacles",[]),
                                          source_ui=_airport_project_metadata())
                            st.session_state["ws_viewer_handoff"]=token
                        except Exception as exc:
                            st.error(f"VIEWER nelze připravit: {exc}")
                    token=st.session_state.get("ws_viewer_handoff")
                    if token:
                        st.markdown(
                            '<a href="?viewer=1&amp;snapshot='+token+'" target="_blank" '
                            'rel="noopener" style="display:block;text-align:center;'
                            'border:1px solid #478eae;background:#193d57;color:#c9f3ff;'
                            'padding:8px;border-radius:7px;text-decoration:none;font-weight:700">'
                            '↗ OTEVŘÍT VÝSLEDEK</a>',unsafe_allow_html=True)

            elif section=="VALIDACE":
                _render_los_validation(result)
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
                        st.session_state.get("obstacles",[])) or config!=result["config"] or
                        (result["config"].radar_mode=="PAR-NG" and
                         _par_model_metadata()!=_par_pattern_metadata(result.get("antenna_pattern"))))
                    st.caption("Výsledek je potřeba přepočítat." if stale
                               else "Výpočet je aktuální.")
                    if st.button("↻ PŘEPOČÍTAT Z ULOŽENÉHO TERÉNU",
                                 use_container_width=True,key="ws_recalculate_cached",
                                 help="Rychle zapracuje přidané, změněné či odstraněné překážky bez dalšího stažení DEM."):
                        try:
                            _recalculate_cached_terrain()
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Přepočet z uloženého DEM selhal; předchozí výsledek zůstal zachován: {exc}")
                st.markdown('<div class="cd-nav-title">PROJEKT A DATA</div>',unsafe_allow_html=True)
                if result is not None:
                    if st.button("⇩ PŘIPRAVIT PRACOVNÍ PROJEKT · .cdproj",
                                 use_container_width=True,key="ws_prepare_snapshot",
                                 help="Snapshot DEM a výpočtu připravit až na vyžádání."):
                        try:
                            st.session_state["ws_snapshot_bytes"]=save_project(
                                result,levels=st.session_state.get("ws_levels",[]),
                                obstacles=st.session_state.get("obstacles",[]),
                                source_ui=_airport_project_metadata(),
                                display=_visual_project_state())
                            st.session_state["ws_snapshot_key"]=(
                                result.get("completed_at"),
                                obstacle_signature(st.session_state.get("obstacles",[])),
                                tuple(st.session_state.get("ws_levels",[])),
                                st.session_state.get("ws_airport_code",""),
                                tuple(r["key"] for r in st.session_state.get("ws_airport_geometry") or []),
                                st.session_state.get("ws_airspace_source_time",""),
                                tuple(sorted(_par_model_metadata().items())),
                                st.session_state.get("ws_par_level_reference","AGL"),
                            )
                        except Exception as exc:
                            st.error(f"Projekt nelze uložit: {exc}")
                    snapshot_key=(
                        result.get("completed_at"),
                        obstacle_signature(st.session_state.get("obstacles",[])),
                        tuple(st.session_state.get("ws_levels",[])),
                        st.session_state.get("ws_airport_code",""),
                        tuple(r["key"] for r in st.session_state.get("ws_airport_geometry") or []),
                        st.session_state.get("ws_airspace_source_time",""),
                        tuple(sorted(_par_model_metadata().items())),
                        st.session_state.get("ws_par_level_reference","AGL"),
                    )
                    if st.session_state.get("ws_snapshot_bytes") and st.session_state.get("ws_snapshot_key")==snapshot_key:
                        st.download_button("STÁHNOUT PRACOVNÍ PROJEKT",
                            data=st.session_state["ws_snapshot_bytes"],
                            file_name="COVERAGEDIAGRAMS_working.cdproj",
                            mime="application/octet-stream",use_container_width=True,
                            key="ws_save_working_project",
                            help="Přenosný snapshot včetně DEM, nezávislý na dočasné cache.")
 
            elif section=="POZICE":
                st.markdown('<div class="cd-nav-title">POZICE / AIRPORT & RANGE</div>',
                            unsafe_allow_html=True)
                st.caption("Práce s polohou a vektorovými vrstvami funguje bez radarového výpočtu.")
                _airport_controls()
                _range_controls()
                _position_nearby_controls()

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

    # The map fills the screen. Status is a floating, non-blocking overlay,
    # not a normal document row above Leaflet that causes map size changes.
    from workspace_floating_layout import FLOATING_EDITOR_CSS
    st.markdown(FLOATING_EDITOR_CSS, unsafe_allow_html=True)
    with st.container(key="cd_editor_status"):
        if result is None:
            st.caption(f"RADAR · {config.lat:.6f}°, {config.lon:.6f}° · "
                       f"{len(st.session_state.get('obstacles',[]))} překážek")
        else:
            is_stale=(result.get("obstacles_signature")!=obstacle_signature(
                st.session_state.get("obstacles",[])) or config!=result["config"] or
                (result["config"].radar_mode=="PAR-NG" and
                 _par_model_metadata()!=_par_pattern_metadata(result.get("antenna_pattern"))))
            if is_stale:
                st.warning("Nastavení nebo překážky se změnily. "
                           "Zobrazené krytí patří k předchozímu výpočtu.")
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
