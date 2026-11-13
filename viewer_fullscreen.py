"""Fullscreen standalone VIEWER: browser-side layer manager and persistent Leaflet."""
from __future__ import annotations

import base64
import gzip
import json

import numpy as np
import radar_core as core
import streamlit as st
import streamlit.components.v1 as components


def render_fullscreen_viewer(layers, styles, center, *, diagnostic_result=None,
                             diagnostic_levels=(), diagnostic_reference="AMSL",
                             snapshot="", studio_url=""):
    """Only mount one map. UI edits, import and filtering never rerun Streamlit."""
    # Base64 avoids closing the embedded script or injecting HTML from imported data.
    # Native grid: no second DEM sampler, no speculative covered points.
    # Compression avoids sending megabytes of repetitive JSON through the iframe.
    diagnostics = None
    if diagnostic_result is not None and (diagnostic_result.get("antenna_pattern") is not None
                                          or not diagnostic_result["config"].csc_enabled):
        result = diagnostic_result
        cfg = result["config"]
        levels = [int(ft) for ft in diagnostic_levels
                  if core.valid_flight_level(cfg.radar_mode, ft)]
        if not levels:
            levels = [int(ft) for ft in core.flight_levels_for(cfg.radar_mode)[:3]]
        levels = list(dict.fromkeys(levels))[:80]
        grid = {
            "az": np.round(result["az"], 6).tolist(),
            "distance": np.round(result["distance"], 3).tolist(),
            "terrain": np.where(np.isfinite(result["terrain"]), result["terrain"], None).tolist(),
            "lower": np.where(np.isfinite(result["lower"]), result["lower"], None).tolist(),
            "upper": np.where(np.isfinite(result["upper"]), result["upper"], None).tolist(),
            "antenna": float(result["antenna"]),
            "k": float(cfg.k),
            "minElev": float(cfg.min_elev),
            "maxElev": float(cfg.max_elev),
            "bearing": float(cfg.bearing_deg),
            "radarMode": str(cfg.radar_mode),
            "reference": "AMSL",
            "sectorEdgeLoss": float(getattr(result.get("antenna_pattern"), "sector_edge_loss_db", 6.0)),
            "rfAssumptions": dict(core.SSR_ASSUMPTIONS) if cfg.radar_mode == "SSR" else None,
            "levels": levels,
            "status": {},
        }
        for ft in levels:
            values = core.status_at_height(result, ft * core.FT_TO_M,
                                           reference=grid["reference"])
            # 2: unknown, 0: blocked, 1: covered.
            grid["status"][str(ft)] = np.where(
                np.isfinite(values), np.asarray(np.nan_to_num(values), dtype=np.uint8), 2
            ).tolist()
        raw = json.dumps(grid, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
        diagnostics = base64.b64encode(gzip.compress(raw, compresslevel=5)).decode("ascii")
    encoded=base64.b64encode(json.dumps({
        "layers":layers,
        "styles":styles,
        "center":[float(center[0]),float(center[1])],
        "radarKnown":diagnostic_result is not None,
        "snapshot":str(snapshot),
        "studioUrl":str(studio_url),
        "diagnostics":diagnostics,
    },ensure_ascii=False,allow_nan=False).encode("utf-8")).decode("ascii")
    page=_HTML.replace("__VIEWER_PAYLOAD__",encoded)
    st.markdown("""<style>
    header[data-testid="stHeader"],[data-testid="stToolbar"],
    [data-testid="stDecoration"],footer,[data-testid="stSidebar"]{display:none!important}
    [data-testid="stAppViewContainer"]{background:#081321!important}
    [data-testid="stMainBlockContainer"],.block-container{
        max-width:none!important;padding:0!important;margin:0!important}
    [data-testid="stMainBlockContainer"] > div,[data-testid="stVerticalBlock"]{
        gap:0!important}
    [data-testid="stIFrame"]{
        width:100vw!important;height:100dvh!important;display:block!important;
        border:0!important}
    iframe[title="cd-fullscreen-viewer"]{height:100dvh!important}
    </style>""",unsafe_allow_html=True)
    # iframe height is also overridden by the viewport rule above.
    components.html(page,height=950,scrolling=False)


_HTML=r"""<!doctype html><html lang="cs"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js"></script>
<style>
*{box-sizing:border-box}html,body,#map{margin:0;width:100%;height:100%;overflow:hidden}
body{font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;background:#071320;color:#eaf2ff}
#map{background:#0e2235}
.leaflet-container{background:#0e2235;font:inherit}
.leaflet-control-zoom{margin-top:74px!important;margin-right:16px!important}
.leaflet-control-zoom a{background:#112842!important;color:#eaf2ff!important;border-color:#35536a!important}
.leaflet-control-attribution{background:#09182bcc!important;color:#b3c8da!important}
.toolbar{position:absolute;z-index:1000;top:14px;left:16px;display:flex;gap:7px;align-items:center;max-width:calc(100vw - 100px)}
.brand{display:flex;align-items:center;gap:9px;padding:10px 14px;background:#0b2035f2;border:1px solid #365676;border-radius:12px;
font-weight:800;letter-spacing:.095em;white-space:nowrap;box-shadow:0 8px 30px #0005}
.brand small{font-weight:500;letter-spacing:0;color:#7fc8e7}
button,.fakebtn{cursor:pointer;font:inherit;color:#ecf7ff;background:#153451;border:1px solid #3b6281;border-radius:9px;padding:9px 12px;white-space:nowrap}
button:hover,.fakebtn:hover{background:#235071;border-color:#6fbbdf}
button.primary{background:#087aaf;border-color:#40b7e7;font-weight:750}
button.ghost{background:#0b2035ef}
button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #63d0ff;outline-offset:2px}
.panel{position:absolute;z-index:1100;top:70px;left:16px;width:365px;max-width:calc(100vw - 32px);
height:min(750px,calc(100dvh - 94px));display:flex;flex-direction:column;
background:#0b2035f7;border:1px solid #456582;border-radius:15px;box-shadow:0 16px 55px #0008;
backdrop-filter:blur(12px)}
.panel.hidden{display:none}
.panel header{display:flex;gap:7px;padding:12px;border-bottom:1px solid #2a4a66;align-items:center}
.panel header strong{flex:1;font-size:13px;letter-spacing:.08em}
.panel header button{padding:5px 10px}
.tabs{display:flex;gap:5px;padding:9px 12px 0}
.tabs button{flex:1;padding:8px 3px;font-size:12px}
.tabs button.active{background:#195f87;border-color:#5bc3e8}
.section{flex:1;overflow:auto;min-height:0;padding:13px}
.section[hidden],[hidden]{display:none!important}
h3{font-size:11px;letter-spacing:.12em;color:#83d8fd;margin:4px 0 13px}
.muted{color:#9bb4c9;font-size:11px;line-height:1.5}
.field{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:10px 0}
.field label{font-size:12px;color:#d7e5f0}
.field input[type=range]{width:140px}
input[type=text],input[type=search],select,input[type=number],textarea{background:#fff!important;color:#000!important;-webkit-text-fill-color:#000!important;caret-color:#000!important;border:1px solid #7e99af;border-radius:7px;padding:9px;min-width:0}
input[type=text]::placeholder,input[type=search]::placeholder,textarea::placeholder{color:#666!important;-webkit-text-fill-color:#666!important;opacity:1}
select{max-width:190px}.wide{width:100%;max-width:none!important}
.actions{display:flex;gap:6px;margin:9px 0}.actions button{flex:1}
input[type=checkbox]{accent-color:#0aa5e8;cursor:pointer}
#layer-list{display:flex;flex-direction:column;gap:7px;overflow:auto;padding-bottom:10px}
.layer{display:grid;grid-template-columns:19px 1fr 31px;align-items:center;gap:8px;padding:9px;
background:#122d46;border:1px solid #2c4b64;border-radius:9px}
.layer.off{opacity:.56}.layer .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
.layer small{display:block;font-size:10px;color:#97b5c9}
.layer button{padding:5px 6px;font-size:13px}
.layer .name{cursor:pointer}
.layer.is-editing{border-color:#63cffa;background:#19425d}
.layer-properties{position:absolute;inset:0;z-index:7;display:flex;flex-direction:column;
 background:#0c2238;border-radius:14px;overflow:hidden}
.layer-properties[hidden]{display:none!important}
.layer-props-head{display:flex;align-items:center;gap:9px;padding:16px 16px 13px;
 background:#122f49;border-bottom:1px solid #355975}
.layer-props-head .layer-props-title{flex:1;min-width:0}
.layer-props-head .layer-props-title strong{display:block;font:750 13px system-ui;color:#f5faff}
.layer-props-head .layer-props-title span{display:block;font:11px system-ui;color:#a9cadb;
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.layer-props-head button{padding:7px 10px}
.layer-props-body{flex:1;min-height:0;overflow:auto;padding:16px;display:flex;
 flex-direction:column;gap:15px;overscroll-behavior:contain}
.layer-props-section{border-radius:11px;border:1px solid #34536d;background:#102c46;
 padding:13px 13px 14px}
.layer-props-section>strong{display:block;margin-bottom:11px;color:#8fdaf6;
 font:750 11px system-ui;letter-spacing:.07em}
.layer-props-control{margin:0 0 15px}
.layer-props-control:last-child{margin-bottom:0}
.layer-props-control label{display:flex;align-items:center;justify-content:space-between;
 gap:12px;margin-bottom:7px;color:#d8e7f2;font:12px system-ui}
.layer-props-value{color:#101f2d;background:#d6edfc;border-radius:5px;
 padding:3px 6px;min-width:42px;text-align:center;font:750 11px system-ui}
.layer-props-control input[type=range]{width:100%;display:block;accent-color:#54caf9;
 cursor:pointer;margin:8px 0 3px}
.layer-props-control input[type=color]{width:100%;height:37px;border-radius:7px;
 padding:3px;border:1px solid #54758e;background:#fff;cursor:pointer}
.layer-props-control select{width:100%;max-width:none!important}
.layer-props-note{font-size:11px;color:#a4c8df;line-height:1.5}
.layer-props-actions{padding:13px 16px;display:grid;grid-template-columns:1fr 1fr;
 gap:8px;border-top:1px solid #355975;background:#10283f}
.layer-props-actions button{white-space:normal;padding:10px 6px}
.layer-props-actions .danger{color:#ffb4be;border-color:#9e5766;background:#532d3f}
.panel{overflow:hidden}
.note{border:1px solid #325772;background:#0b2942;border-radius:9px;padding:9px 10px;margin:10px 0;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}
.note.error{border-color:#b65a61;color:#ffb2b8}
.inspection{position:absolute;right:16px;top:72px;z-index:1150;width:min(540px,calc(100vw - 32px));
 max-height:calc(100dvh - 135px);overflow:auto;padding:12px 15px;background:#0b2035f7;
 border:1px solid #4a7d9a;border-radius:12px;box-shadow:0 15px 40px #0009}
.inspection header{display:flex;align-items:center;justify-content:space-between;color:#85d9ff;font-size:12px;letter-spacing:.05em}
.inspection header button{padding:4px 10px}.inspection svg{display:block;width:100%;background:#07182a;border-radius:7px;margin:10px 0}
.inspection #inspection-details{font-size:12px;white-space:pre-line}
@media(max-width:680px){.inspection{top:63px;right:8px;width:calc(100vw - 16px);max-height:50dvh}}
.status{position:absolute;bottom:22px;right:16px;z-index:1000;
background:#0a2136e8;border:1px solid #315873;padding:7px 11px;border-radius:9px;
font-size:11px;pointer-events:none;max-width:50vw}
#drop{position:absolute;inset:0;z-index:2000;background:#071e34cc;border:4px dashed #5acfff;display:none;place-items:center;font-size:25px;font-weight:800;pointer-events:none}
#drop.on{display:grid}
#file{display:none}
@media(max-width:680px){.brand small{display:none}.brand{padding:9px}.toolbar{gap:5px;left:8px;top:8px}.toolbar button{padding:9px 8px;font-size:11px}
.panel{left:8px;top:60px;width:calc(100vw - 16px);height:calc(100dvh - 77px)}.status{bottom:16px;right:8px}}
</style></head><body>
<div id="map" role="application" aria-label="Interaktivní mapa VIEWER"></div>
<div class="toolbar">
  <div class="brand">◈ VIEWER <small>GEOSPATIAL WORKSPACE</small></div>
  <button id="panel-toggle" class="primary" aria-expanded="true">☷ Nastavení</button>
  <button id="quick-open" class="ghost">＋ Soubor</button>
  <button id="fit" class="ghost">◎ Přiblížit data</button>
  <button id="inspect" class="ghost" aria-pressed="false">⌖ BOD / PROFIL</button>
  <button id="print-studio" class="ghost" hidden>⇩ Export studio</button>
</div>
<div class="panel" id="panel">
 <header><strong>MAP WORKSPACE</strong><span id="count" class="muted">0 vrstev</span><button id="close" aria-label="Zavřít panel">×</button></header>
 <div class="tabs"><button class="active" data-tab="layers">VRSTVY</button><button data-tab="source">IMPORT</button><button data-tab="map">MAPA</button></div>
 <section class="section" id="tab-layers">
   <input id="search" type="search" class="wide" placeholder="Filtrovat názvy vrstev / objektů…">
   <div class="actions"><button id="all">Vše</button><button id="none">Nic</button><button id="invert">Invertovat</button></div>
   <div class="muted" id="layer-stats"></div><div class="muted" style="margin:4px 0 9px">Dvojklik na vrstvu nebo ⚙ otevře grafické nastavení.</div><div id="layer-list"></div>
 </section>
 <section class="section" id="tab-source" hidden>
   <h3>NAČTENÍ GEODAT</h3>
   <button id="load" class="primary wide">＋ Načíst KML / KMZ / GeoJSON / CDVIEW</button>
   <p class="muted">Maximálně 200 MB na soubor. Lze také přetáhnout soubory přímo do mapy. Importované vrstvy se přidají k existujícím; projekt CDVIEW obnoví celé pracovní prostředí.</p>
   <div class="actions"><button id="clear">Odstranit všechny vrstvy</button></div>
   <div id="notice" class="note">Mapové ovládání běží přímo v prohlížeči. Posouvání, zoom a změny vrstev neaktualizují Streamlit.</div>
 </section>
 <section class="section" id="tab-map" hidden>
   <h3>MAPOVÁ KOMPOZICE</h3>
   <div class="field"><label for="base">Podkladová mapa</label><select id="base">
     <option value="osm">OpenStreetMap</option><option value="imagery">Esri World Imagery</option>
     <option value="topo">Esri Topographic</option><option value="hillshade">Esri World Hillshade</option>
     <option value="opentopo">OpenTopoMap</option></select></div>
   <div class="field"><label for="labels">Popisky objektů</label><input id="labels" type="checkbox" checked></div>
   <div class="field"><label for="legend">Legenda</label><input id="legend" type="checkbox" checked></div>
   <div class="field"><label for="range-on">RANGE kružnice</label><input id="range-on" type="checkbox"></div>
   <div class="field"><label for="range">RANGE [NM]</label><input id="range" type="range" min="1" max="260" value="20"><strong id="range-text">20</strong></div>
   <div class="muted" id="range-center">Střed: radar</div>
   <h3 style="margin-top:24px">OBLAST PRO STAŽENÍ DAT</h3>
   <div class="note" id="extent-source">Hledám hranici nejvyšší vypočtené letové hladiny…</div>
   <div class="actions"><button id="extent-auto" class="primary">◎ Podle nejvyšší FL</button><button id="extent-fit">Zobrazit oblast</button></div>
   <div class="field"><label for="extent-south">Jih / LAT min</label><input id="extent-south" type="number" min="-90" max="90" step=".000001" placeholder="S"></div>
   <div class="field"><label for="extent-north">Sever / LAT max</label><input id="extent-north" type="number" min="-90" max="90" step=".000001" placeholder="N"></div>
   <div class="field"><label for="extent-west">Západ / LON min</label><input id="extent-west" type="number" min="-180" max="180" step=".000001" placeholder="W"></div>
   <div class="field"><label for="extent-east">Východ / LON max</label><input id="extent-east" type="number" min="-180" max="180" step=".000001" placeholder="E"></div>
   <div class="actions" hidden><button id="extent-export" class="ghost wide">⇩ STÁHNOUT OBLAST · GEOJSON</button></div>
   <p class="muted">Obdélník přesně zahrnuje vnější okraj polygonů krytí nejvyšší dostupné FL. Hodnoty lze upravit ručně. GeoJSON určuje geografickou oblast pro následné stažení DEM; neobsahuje samotný výškový rastr.</p>
   <h3 style="margin-top:24px" hidden>EXPORT</h3>
   <div class="actions" hidden><button id="save-geo">GeoJSON</button><button id="save-project">Projekt CDVIEW</button></div>

 </section>
</div>
<aside id="inspection" class="inspection" hidden>
  <header><strong>⌖ ANALÝZA BODU / LINE OF SIGHT</strong><button id="inspection-close" aria-label="Zavřít analýzu">×</button></header>
  <div id="native-level-row" class="field" hidden><label for="inspection-level">Hladina z výpočtu [ft]</label><select id="inspection-level"></select></div>
  <div id="dem-controls">
    <div class="note">Bez výpočtu z EDITORU se automaticky načte DEM pro trasu radar → bod. Výsledkem je pouze geometrická kontrola LOS, nikoli RF krytí.</div>
    <div class="field"><label for="dem-antenna">Výška antény [m AGL]</label><input id="dem-antenna" type="number" min="0.1" max="5000" step="1" value="20"></div>
    <div class="field"><label for="dem-target">Výška cíle [ft AMSL]</label><select id="dem-target"><option value="100">100 ft AMSL</option><option value="200">200 ft AMSL</option><option value="300">300 ft AMSL</option><option value="400">400 ft AMSL</option><option value="500">500 ft AMSL</option><option value="600">600 ft AMSL</option><option value="700">700 ft AMSL</option><option value="800">800 ft AMSL</option><option value="900">900 ft AMSL</option><option value="1000">1 000 ft AMSL</option><option value="1100">1 100 ft AMSL</option><option value="1200">1 200 ft AMSL</option><option value="1300">1 300 ft AMSL</option><option value="1400">1 400 ft AMSL</option><option value="1500">1 500 ft AMSL</option><option value="1600">1 600 ft AMSL</option><option value="1700">1 700 ft AMSL</option><option value="1800">1 800 ft AMSL</option><option value="1900">1 900 ft AMSL</option><option value="2000">2 000 ft AMSL</option><option value="2100">2 100 ft AMSL</option><option value="2200">2 200 ft AMSL</option><option value="2300">2 300 ft AMSL</option><option value="2400">2 400 ft AMSL</option><option value="2500">2 500 ft AMSL</option><option value="2600">2 600 ft AMSL</option><option value="2700">2 700 ft AMSL</option><option value="2800">2 800 ft AMSL</option><option value="2900">2 900 ft AMSL</option><option value="3000" selected>3 000 ft AMSL</option><option value="3100">3 100 ft AMSL</option><option value="3200">3 200 ft AMSL</option><option value="3300">3 300 ft AMSL</option><option value="3400">3 400 ft AMSL</option><option value="3500">3 500 ft AMSL</option><option value="3600">3 600 ft AMSL</option><option value="3700">3 700 ft AMSL</option><option value="3800">3 800 ft AMSL</option><option value="3900">3 900 ft AMSL</option><option value="4000">4 000 ft AMSL</option><option value="4100">4 100 ft AMSL</option><option value="4200">4 200 ft AMSL</option><option value="4300">4 300 ft AMSL</option><option value="4400">4 400 ft AMSL</option><option value="4500">4 500 ft AMSL</option><option value="4600">4 600 ft AMSL</option><option value="4700">4 700 ft AMSL</option><option value="4800">4 800 ft AMSL</option><option value="4900">4 900 ft AMSL</option><option value="5000">5 000 ft AMSL</option><option value="5100">5 100 ft AMSL</option><option value="5200">5 200 ft AMSL</option><option value="5300">5 300 ft AMSL</option><option value="5400">5 400 ft AMSL</option><option value="5500">5 500 ft AMSL</option><option value="5600">5 600 ft AMSL</option><option value="5700">5 700 ft AMSL</option><option value="5800">5 800 ft AMSL</option><option value="5900">5 900 ft AMSL</option><option value="6000">6 000 ft AMSL</option><option value="6100">6 100 ft AMSL</option><option value="6200">6 200 ft AMSL</option><option value="6300">6 300 ft AMSL</option><option value="6400">6 400 ft AMSL</option><option value="6500">6 500 ft AMSL</option><option value="6600">6 600 ft AMSL</option><option value="6700">6 700 ft AMSL</option><option value="6800">6 800 ft AMSL</option><option value="6900">6 900 ft AMSL</option><option value="7000">7 000 ft AMSL</option><option value="7100">7 100 ft AMSL</option><option value="7200">7 200 ft AMSL</option><option value="7300">7 300 ft AMSL</option><option value="7400">7 400 ft AMSL</option><option value="7500">7 500 ft AMSL</option><option value="7600">7 600 ft AMSL</option><option value="7700">7 700 ft AMSL</option><option value="7800">7 800 ft AMSL</option><option value="7900">7 900 ft AMSL</option><option value="8000">8 000 ft AMSL</option><option value="8100">8 100 ft AMSL</option><option value="8200">8 200 ft AMSL</option><option value="8300">8 300 ft AMSL</option><option value="8400">8 400 ft AMSL</option><option value="8500">8 500 ft AMSL</option><option value="8600">8 600 ft AMSL</option><option value="8700">8 700 ft AMSL</option><option value="8800">8 800 ft AMSL</option><option value="8900">8 900 ft AMSL</option><option value="9000">9 000 ft AMSL</option></select></div>
    <div class="field"><label for="dem-k">Efektivní poloměr Země (k)</label><input id="dem-k" type="number" min="0.5" max="3" step=".01" value="1.333333"></div>
    <button id="dem-set-radar" class="ghost wide">⌖ Zadat polohu radaru kliknutím do mapy</button>
    <div id="dem-source" class="muted">Zdroj: Copernicus GLO-90 přes Open-Meteo Elevation API. Přenos DEM může vyžadovat internetové připojení.</div>
  </div>
  <div id="inspection-result" class="note">Klikni na libovolný bod v mapě.</div>
  <svg id="inspection-profile" viewBox="0 0 520 184" role="img" aria-label="Terénní profil a spojnice přímé viditelnosti"></svg>
  <div id="inspection-details" class="muted"></div>
  <div class="actions" id="profile-exports" hidden>
    <button id="profile-csv" class="primary">⇩ PROFIL CSV</button>
    <button id="profile-svg" class="ghost">⇩ GRAF SVG</button>
    <button id="profile-geo" class="ghost">⇩ TRASA GEOJSON</button>
  </div>
</aside>
<div id="status" class="status">Načítám mapu…</div>
<div id="drop">PUSŤ SOUBORY DO MAPY</div><input id="file" type="file" accept=".kml,.kmz,.json,.geojson,.cdview" multiple>
<script>
const DATA=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob("__VIEWER_PAYLOAD__"),c=>c.charCodeAt(0))));
const $=id=>document.getElementById(id);
const BASES={
 osm:["https://tile.openstreetmap.org/{z}/{x}/{y}.png","© OpenStreetMap contributors"],
 imagery:["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}","Tiles © Esri"],
 topo:["https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}","Tiles © Esri"],
 hillshade:["https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}","Hillshade © Esri and data providers"],
 opentopo:["https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png","© OpenTopoMap, OpenStreetMap"]
};
const COLORS=["#3fa7fa","#21d7bf","#dc8aff","#ffb058","#fc647e","#a6d67b"];
let layers=new Map(),map=null,base=null,rangeShape=null,openedEditor=null,vectorRenderer=null;
let grid=null, inspectEnabled=false, selectedPoint=null, inspectionLine=null, inspectionMarker=null;
let lastProfile=null;
let placingRadar=false, demController=null, demRequest=0, radarMarker=null;
let extentRectangle=null,extentLevel=null,extentSelectedFeatures=[],extentGeometry=null;
let radarKnown=Boolean(DATA.radarKnown);
const demCache=new Map();
let setting={base:"hillshade",labels:true,legend:true,range:false,nm:20};
let layerSeq=0,chosenBase="hillshade",radarCenter=DATA.center||[50,15],legendControl=null;
const escapeHTML=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const filename=s=>String(s||"import").slice(0,180);
const status=t=>{$("status").textContent=t};
function notify(t,error=false){$("notice").textContent=t;$("notice").classList.toggle("error",error);status(t)}
function validFeature(f){return f&&f.type==="Feature"&&f.geometry&&typeof f.geometry.type==="string"}
function initialStyle(s,i){
 const bounded=(value,fallback,min,max)=>value===undefined||value===null||value===""?
    fallback:(Number.isFinite(Number(value))?Math.min(max,Math.max(min,Number(value))):fallback);
 return {
  show:s?.show!==false,
  color:/^#[0-9a-f]{6}$/i.test(s?.color||"")?s.color:COLORS[i%COLORS.length],
  opacity:bounded(s?.opacity,.35,0,1),
  strokeOpacity:bounded(s?.strokeOpacity,1,0,1),
  width:bounded(s?.width,2,.5,12),
  radius:bounded(s?.radius,4,1,16),
  dash:["solid","dash","dot"].includes(s?.dash)?s.dash:"solid"
 };
}
function addLayer(name,features,style,rerender=true){
 if(!Array.isArray(features))return;
 const good=features.filter(validFeature);
 if(!good.length)return;
 let unique=String(name||"Layer");let index=2;while(layers.has(unique))unique=String(name||"Layer")+" ("+(index++)+")";
 layers.set(unique,{name:unique,features:good,style:initialStyle(style,layerSeq++),geo:null,attached:false});
 if(rerender){refreshList();syncAll();fitAll();updateExtentPreset()}
}
function resetLayers(){closeLayerProperties();for(const o of layers.values())if(o.geo)map.removeLayer(o.geo);layers.clear();openedEditor=null}
function styleOf(o){return {
 color:o.style.color,weight:o.style.width,opacity:o.style.strokeOpacity,
 fillColor:o.style.color,fillOpacity:o.style.opacity,
 dashArray:o.style.dash==="dash"?"8 5":o.style.dash==="dot"?"2 5":null,
 radius:o.style.radius
}}
function ensureGeo(o){
 if(o.geo)return;
 o.geo=L.geoJSON({type:"FeatureCollection",features:o.features},{
  renderer:vectorRenderer,
  style:()=>styleOf(o),
  pointToLayer:(f,ll)=>L.circleMarker(ll,styleOf(o)),
  onEachFeature:(f,l)=>{const p=f.properties||{};const name=p.name||p.Name||p.title;
    if(name)l.bindTooltip(escapeHTML(name),{sticky:true,permanent:false});
    if(p.description)l.bindPopup("<b>"+escapeHTML(name||o.name)+"</b><p>"+escapeHTML(p.description).slice(0,1200)+"</p>")
  }
 });
}
function syncOne(o){if(o.style.show){ensureGeo(o);if(!map.hasLayer(o.geo))o.geo.addTo(map);o.geo.setStyle(styleOf(o))}
 else if(o.geo&&map.hasLayer(o.geo))map.removeLayer(o.geo)}
function syncAll(){for(const o of layers.values())syncOne(o);refreshLegend();updateCount()}
function updateCount(){let n=0;for(const o of layers.values())if(o.style.show)n++;
 $("count").textContent=n+" / "+layers.size+" vrstev";$("layer-stats").textContent="Zobrazeno "+n+" z "+layers.size+" vrstev"}
function renderLayerRow(o,filter){
 const search=(filter||"").toLocaleLowerCase();
 const nameMatch=o.name.toLocaleLowerCase().includes(search);
 const matched=search?o.features.filter(f=>String(f.properties?.name||f.properties?.Name||"").toLocaleLowerCase().includes(search)):null;
 if(search&&!nameMatch&&!matched.length)return null;
 const row=document.createElement("div");row.className="layer"+(o.style.show?"":" off");
 row.title="Dvojklik otevře grafické vlastnosti vrstvy";
 row.addEventListener("dblclick",e=>{
   if(e.target.closest("button,input,.layer-editor"))return;
   e.preventDefault();openLayerProperties(o.name);
 });
 const check=document.createElement("input");check.type="checkbox";check.checked=o.style.show;check.setAttribute("aria-label","Zobrazit "+o.name);
 check.addEventListener("change",()=>{o.style.show=check.checked;syncOne(o);refreshLegend();updateCount();row.classList.toggle("off",!check.checked)});
 const desc=document.createElement("div");desc.innerHTML='<div class="name" title="'+escapeHTML(o.name)+'">'+escapeHTML(o.name)+'</div><small>'+o.features.length.toLocaleString("cs")+" objektů"+(matched&&!nameMatch?" · shoda "+matched.length:"")+"</small>";
 const edit=document.createElement("button");edit.textContent="⚙";edit.setAttribute("aria-label","Vlastnosti "+o.name);edit.title="Upravit grafické vlastnosti";
 edit.addEventListener("click",()=>openLayerProperties(o.name));
 row.append(check,desc,edit);
 return row;
}
function closeLayerProperties(){
 openedEditor=null;
 const el=$("layer-properties");
 if(el){el.hidden=true;el.replaceChildren();}
 for(const node of $("layer-list").querySelectorAll(".is-editing"))node.classList.remove("is-editing");
}
function openLayerProperties(name){
 const o=layers.get(name);
 if(!o)return;
 openedEditor=name;
 const host=$("panel");
 if(!host.classList.contains("hidden")){}else{
   host.classList.remove("hidden");
   $("panel-toggle").setAttribute("aria-expanded","true");
 }
 let drawer=$("layer-properties");
 if(!drawer){
   drawer=document.createElement("div");
   drawer.id="layer-properties";
   drawer.className="layer-properties";
   drawer.setAttribute("role","region");
   drawer.setAttribute("aria-label","Grafické vlastnosti vrstvy");
   host.append(drawer);
 }
 drawer.hidden=false;
 drawer.replaceChildren();
 for(const node of $("layer-list").querySelectorAll(".layer"))node.classList.remove("is-editing");
 const title=document.createElement("div");title.className="layer-props-title";
 const h=document.createElement("strong");h.textContent="GRAFICKÉ VLASTNOSTI";
 const sub=document.createElement("span");sub.textContent=o.name+" · "+o.features.length.toLocaleString("cs")+" objektů";
 title.append(h,sub);
 const heading=document.createElement("div");heading.className="layer-props-head";
 const back=document.createElement("button");back.textContent="← ZPĚT";back.type="button";
 back.addEventListener("click",closeLayerProperties);
 heading.append(back,title);drawer.append(heading);
 const body=document.createElement("div");body.className="layer-props-body";drawer.append(body);
 function section(name){
   const box=document.createElement("section");box.className="layer-props-section";
   const caption=document.createElement("strong");caption.textContent=name;box.append(caption);
   body.append(box);return box;
 }
 const visual=section("VÝPLŇ A OBRAZ");
 const contour=section("OBRYS A BODY");
 const apply=()=>{
   if(o.geo)o.geo.setStyle(styleOf(o));
   refreshLegend();
 };
 function control(parent,label,key,type,min,max,step,format){
   const wrap=document.createElement("div");wrap.className="layer-props-control";
   const lab=document.createElement("label");lab.textContent=label;
   const id="layerprop-"+key;
   lab.htmlFor=id;
   const shown=document.createElement("span");shown.className="layer-props-value";
   if(type==="range")lab.append(shown);
   let el=document.createElement(type==="select"?"select":"input");
   el.id=id;if(type!=="select")el.type=type;
   if(type==="range"){el.min=min;el.max=max;el.step=step;}
   if(type==="select"){
     for(const [value,text] of [["solid","Plná"],["dash","Čárkovaná"],["dot","Tečkovaná"]]){
       const option=document.createElement("option");option.value=value;option.textContent=text;el.append(option);
     }
   }
   const view=()=>type==="range"
     ?(format==="percent"?Math.round(Number(o.style[key])*100)+" %":
       Number(o.style[key]).toFixed(key==="width"?1:0)+" px")
     :String(o.style[key]);
   el.value=type==="range"&&format==="percent"
     ?Math.round(o.style[key]*100):o.style[key];
   shown.textContent=view();
   const change=()=>{
     o.style[key]=type==="color"||type==="select"?el.value:
       format==="percent"?Number(el.value)/100:Number(el.value);
     shown.textContent=view();
     apply();
   };
   el.addEventListener("input",change);el.addEventListener("change",change);
   wrap.append(lab,el);parent.append(wrap);return el;
 }
 control(visual,"Barva vrstvy","color","color");
 control(visual,"Průhlednost výplně","opacity","range",0,100,5,"percent");
 control(contour,"Průhlednost obrysu","strokeOpacity","range",0,100,5,"percent");
 control(contour,"Šířka obrysu","width","range",.5,12,.5,"px");
 control(contour,"Velikost bodu","radius","range",1,16,1,"px");
 control(contour,"Styl obrysu","dash","select");
 const note=document.createElement("p");note.className="layer-props-note";
 note.textContent="Změny se promítnou do mapy ihned, bez jejího restartu. Uložením projektu CDVIEW se zachovají i tyto vlastnosti.";
 body.append(note);
 const actions=document.createElement("div");actions.className="layer-props-actions";
 const reset=document.createElement("button");reset.type="button";reset.textContent="↺ VÝCHOZÍ STYL";
 reset.addEventListener("click",()=>{
   const priorShow=o.style.show;
   o.style=initialStyle(null,0);o.style.show=priorShow;
   apply();openLayerProperties(o.name);
 });
 const remove=document.createElement("button");remove.type="button";
 remove.className="danger";remove.textContent="ODSTRANIT VRSTVU";
 remove.addEventListener("click",()=>{
   if(o.geo)map.removeLayer(o.geo);
   layers.delete(o.name);closeLayerProperties();
   refreshList();refreshLegend();updateCount();updateExtentPreset();
 });
 actions.append(reset,remove);drawer.append(actions);
}
function refreshList(){
 const list=$("layer-list");list.replaceChildren();const filter=$("search").value.trim();
 for(const o of layers.values()){const row=renderLayerRow(o,filter);if(row)list.appendChild(row)}
 updateCount();
}
function refreshLegend(){
 if(legendControl){map.removeControl(legendControl);legendControl=null}
 if(!setting.legend)return;
 const active=[...layers.values()].filter(o=>o.style.show);
 if(!active.length)return;
 legendControl=L.control({position:"bottomleft"});
 legendControl.onAdd=()=>{const box=L.DomUtil.create("div","viewer-legend");
 box.style.cssText="max-height:210px;overflow:auto;max-width:290px;background:#0b2035ed;border:1px solid #496a84;border-radius:9px;padding:9px 11px;color:#ecf7ff;font:11px system-ui";
 const top=document.createElement("strong");top.textContent="VRSTVY · "+active.length;box.append(top);
 for(const o of active.slice(0,35)){const div=document.createElement("div");div.style.cssText="display:flex;gap:6px;margin-top:5px;align-items:center";
 const swatch=document.createElement("i");swatch.style.cssText="width:13px;height:8px;background:"+o.style.color+";display:inline-block;flex-shrink:0";
 const txt=document.createElement("span");txt.textContent=o.name;div.append(swatch,txt);box.append(div)}
 L.DomEvent.disableClickPropagation(box);return box};legendControl.addTo(map)
}
function fitAll(){
 const group=L.featureGroup([...layers.values()].filter(o=>o.style.show&&o.geo).map(o=>o.geo));
 try{const b=group.getBounds();if(b.isValid())map.fitBounds(b.pad(.08),{animate:false,maxZoom:12});else map.setView(radarCenter,8,{animate:false})}
 catch(e){status("Rozsah dat nelze určit: "+e.message)}
}
function selectBase(k){
 if(!(k in BASES))return;
 if(base)map.removeLayer(base);
 chosenBase=k;setting.base=k;
 const [url,attr]=BASES[k];base=L.tileLayer(url,{attribution:attr,maxZoom:19,updateWhenIdle:true,
   keepBuffer:4,crossOrigin:false}).addTo(map);base.bringToBack();$("base").value=k;
}
function wgs84Destination(latDeg,lonDeg,azDeg,distance){
 // Vincenty direct problem on WGS84, distance in metres, azimuth clockwise from true north.
 const a=6378137,f=1/298.257223563,b=a*(1-f);
 const phi=latDeg*Math.PI/180,alpha1=azDeg*Math.PI/180;
 const U1=Math.atan((1-f)*Math.tan(phi)),sinU1=Math.sin(U1),cosU1=Math.cos(U1);
 const sinA1=Math.sin(alpha1),cosA1=Math.cos(alpha1);
 const sigma1=Math.atan2(Math.tan(U1),cosA1);
 const sinAlpha=cosU1*sinA1,cosSqAlpha=1-sinAlpha*sinAlpha;
 const uSq=cosSqAlpha*(a*a-b*b)/(b*b);
 const A=1+uSq/16384*(4096+uSq*(-768+uSq*(320-175*uSq)));
 const B=uSq/1024*(256+uSq*(-128+uSq*(74-47*uSq)));
 let sigma=distance/(b*A),delta=0;
 for(let i=0;i<40;i++){
   const cos2=Math.cos(2*sigma1+sigma),sinS=Math.sin(sigma),cosS=Math.cos(sigma);
   delta=B*sinS*(cos2+B/4*(cosS*(-1+2*cos2*cos2)-
     B/6*cos2*(-3+4*sinS*sinS)*(-3+4*cos2*cos2)));
   const next=distance/(b*A)+delta;
   if(Math.abs(next-sigma)<1e-12){sigma=next;break}
   sigma=next;
 }
 const sinS=Math.sin(sigma),cosS=Math.cos(sigma);
 const tmp=sinU1*sinS-cosU1*cosS*cosA1;
 const phi2=Math.atan2(sinU1*cosS+cosU1*sinS*cosA1,
   (1-f)*Math.sqrt(sinAlpha*sinAlpha+tmp*tmp));
 const lambda=Math.atan2(sinS*sinA1,cosU1*cosS-sinU1*sinS*cosA1);
 const C=f/16*cosSqAlpha*(4+f*(4-3*cosSqAlpha));
 const L=lambda-(1-C)*f*sinAlpha*(sigma+C*sinS*
   (Math.cos(2*sigma1+sigma)+C*cosS*(-1+2*Math.cos(2*sigma1+sigma)**2)));
 return [phi2*180/Math.PI,((lonDeg+L*180/Math.PI+540)%360)-180];
}
function updateRange(){
 if(rangeShape){map.removeLayer(rangeShape);rangeShape=null}
 const nm=Number($("range").value);setting.nm=nm;$("range-text").textContent=nm;
 if(!$("range-on").checked)return;
 const pts=[];
 for(let a=0;a<=360;a+=2)pts.push(wgs84Destination(radarCenter[0],radarCenter[1],a,nm*1852));
 rangeShape=L.polyline(pts,{color:"#4fd5ff",weight:2,dashArray:"7,5",interactive:false}).addTo(map);
}
function geometry(node){
 const ns="http://www.opengis.net/kml/2.2";
 const find=(n,tag)=>n.getElementsByTagNameNS(ns,tag)[0]||n.getElementsByTagName(tag)[0];
 const all=(n,tag)=>[...n.getElementsByTagName("*")].filter(x=>x.localName===tag);
 const coords=n=>String(find(n,"coordinates")?.textContent||"").trim().split(/\s+/).map(s=>s.split(",").map(Number)).filter(v=>v.length>=2&&v.every(Number.isFinite));
 const multi=[...node.children].find(x=>x.localName==="MultiGeometry");
 if(multi){const geometries=[...multi.children].map(geometry).filter(Boolean);
   return geometries.length?{type:"GeometryCollection",geometries}:null}
 const point=node.localName==="Point"?node:find(node,"Point");if(point){const c=coords(point);return c.length?{type:"Point",coordinates:c[0]}:null}
 const line=node.localName==="LineString"?node:find(node,"LineString");if(line){const c=coords(line);return c.length>1?{type:"LineString",coordinates:c}:null}
 const poly=node.localName==="Polygon"?node:find(node,"Polygon");if(poly){
   const outer=find(poly,"outerBoundaryIs");const rings=[];
   if(outer)rings.push(coords(outer));for(const inner of all(poly,"innerBoundaryIs"))rings.push(coords(inner));
   return rings[0]?.length>=3?{type:"Polygon",coordinates:rings}:null}
 return null;
}
function parseKML(xml,file){
 const doc=new DOMParser().parseFromString(xml,"application/xml");
 if(doc.querySelector("parsererror"))throw Error("Neplatný XML/KML");
 const ns="http://www.opengis.net/kml/2.2";
 const matches=(el,n)=>el.localName===n;
 const first=(el,n)=>[...el.children].find(x=>matches(x,n));
 const name=el=>first(el,"name")?.textContent?.trim();
 const groups=new Map();
 function traverse(node,group){
  for(const child of node.children){
   if(matches(child,"Document"))traverse(child,group);
   else if(matches(child,"Folder"))traverse(child,name(child)||group);
   else if(matches(child,"Placemark")){
    const geo=geometry(child);if(!geo)continue;
    if(!groups.has(group))groups.set(group,[]);
    groups.get(group).push({type:"Feature",properties:{name:name(child)||"Unnamed",source:file,
       description:first(child,"description")?.textContent||""},geometry:geo});
   }
  }
 }
 traverse(doc.documentElement,"Imported");return groups;
}
async function loadFile(file){
 if(file.size>200*1024*1024)throw Error("Soubor přesahuje limit 200 MB");
 const lower=file.name.toLowerCase();
 if(lower.endsWith(".cdview")){
  if(!window.JSZip)throw Error("Modul JSZip není dostupný");
  const zip=await JSZip.loadAsync(file);const member=zip.file("viewer.json");
  if(!member)throw Error("CDVIEW neobsahuje viewer.json");
  const raw=await member.async("string");if(raw.length>150*1024*1024)throw Error("Projekt je příliš velký");
  const obj=JSON.parse(raw);
  if(obj.format!=="COVERAGEDIAGRAMS_VIEWER"||obj.version!==1||!obj.layers||!obj.styles)throw Error("Neplatný CDVIEW projekt");
  resetLayers();let idx=0;
  for(const [name,features] of Object.entries(obj.layers)){
    if(++idx>300)throw Error("Příliš mnoho vrstev");addLayer(name,features,obj.styles[name],false)}
  setting.base=BASES[obj.settings?.viewer_basemap]?obj.settings.viewer_basemap:(
    Object.keys(BASES).includes(obj.settings?.base)?obj.settings.base:"hillshade");
  const site=obj.settings?.radar_site;
  if(Array.isArray(site)&&site.length===2)setRadarSite(Number(site[0]),Number(site[1]),"CDVIEW");
  else detectRadarSiteFromLayers();
  selectBase(setting.base);refreshList();syncAll();fitAll();updateExtentPreset();
  return "Projekt načten: "+layers.size+" vrstev";
 }
 let xml=null;
 if(lower.endsWith(".kmz")){
  if(!window.JSZip)throw Error("Modul JSZip není dostupný");
  const zip=await JSZip.loadAsync(file);const names=Object.keys(zip.files).filter(n=>n.toLowerCase().endsWith(".kml"));
  if(!names.length)throw Error("KMZ neobsahuje KML");
  const member=zip.file(names.find(n=>n.toLowerCase().endsWith("/doc.kml"))||names[0]);
  if(member._data?.uncompressedSize>200*1024*1024)throw Error("Rozbalený KML v KMZ přesahuje 200 MB");
  xml=await member.async("string");
 }else if(lower.endsWith(".kml"))xml=await file.text();
 if(xml!==null){
  const groups=parseKML(xml,file.name);for(const [name,features] of groups)addLayer(file.name+" / "+name,features,null,false);
 }else if(lower.endsWith(".geojson")||lower.endsWith(".json")){
  const obj=JSON.parse(await file.text());
  const fs=obj.type==="FeatureCollection"?obj.features:obj.type==="Feature"?[obj]:null;
  if(!Array.isArray(fs))throw Error("Nepodporovaný GeoJSON");
  addLayer(file.name,fs,null,false);
 }else throw Error("Nepodporovaný formát");
 detectRadarSiteFromLayers();refreshList();syncAll();fitAll();updateExtentPreset();return "Načteno: "+file.name;
}
async function importFiles(files){
 let messages=[],errors=[];
 for(const f of [...files]){try{messages.push(await loadFile(f))}catch(e){errors.push(filename(f)+": "+e.message)}}
 notify([...messages,...errors].join("\n")||"Žádná data",errors.length>0);
}
function download(name,blob){
 const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=name;
 document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500)
}
async function saveCDView(){
 if(!window.JSZip){notify("JSZip není dostupný",true);return}
 const data={format:"COVERAGEDIAGRAMS_VIEWER",version:1,layers:{},styles:{},
  settings:{base:setting.base,viewer_basemap:setting.base,viewer_mode:"2D MAPA",
   viewer_legend:setting.legend,viewer_north:true,
   radar_site:radarKnown?[...radarCenter]:null}};
 for(const o of layers.values()){data.layers[o.name]=o.features;data.styles[o.name]=o.style}
 const zip=new JSZip();zip.file("viewer.json",JSON.stringify(data));
 download("COVERAGEDIAGRAMS_viewer.cdview",await zip.generateAsync({type:"blob",compression:"DEFLATE"}));
}
function selectedCoverageLevel(layerName){
 // Only radar coverage layers; unrelated imported/airport layer names are ignored.
 const label=String(layerName);
 if(!/^RADAR\s*\//i.test(label))return null;
 const match=label.match(/(?:^|\/)\s*([\d\s,.]+)\s*ft\b/i);
 if(!match)return null;
 const ft=Number(match[1].replace(/[\s,.]/g,""));
 return Number.isFinite(ft)&&ft>=0?ft:null;
}
function coverageCoordinatePairs(geometry,output){
 if(!geometry)return;
 if(geometry.type==="GeometryCollection"){
  for(const child of geometry.geometries||[])coverageCoordinatePairs(child,output);
  return;
 }
 if(!["Polygon","MultiPolygon"].includes(geometry.type))return;
 const visit=value=>{
  if(!Array.isArray(value))return;
  if(value.length>=2&&typeof value[0]==="number"&&typeof value[1]==="number"){
   if(Number.isFinite(value[0])&&Number.isFinite(value[1])&&
      Math.abs(value[0])<=180&&Math.abs(value[1])<=90)output.push(value);
   return;
  }
  for(const child of value)visit(child);
 };
 visit(geometry.coordinates);
}
function boundsFromHighestFlightLevel(){
 let top=-Infinity;const candidates=[];
 for(const layer of layers.values()){
  const level=selectedCoverageLevel(layer.name);
  if(level===null)continue;
  const points=[];
  for(const feature of layer.features)coverageCoordinatePairs(feature.geometry,points);
  if(!points.length)continue;
  if(level>top){top=level;candidates.length=0}
  if(level===top)candidates.push({layer,points});
 }
 if(!candidates.length)return null;
 let west=Infinity,east=-Infinity,south=Infinity,north=-Infinity;
 for(const item of candidates){
  for(const [lon,lat] of item.points){
   if(lon<west)west=lon;
   if(lon>east)east=lon;
   if(lat<south)south=lat;
   if(lat>north)north=lat;
  }
 }
 if(!(south<north&&west<east))return null;
 // A conventional bbox would span nearly the entire globe at the dateline.
 if(east-west>180)return {invalid:"Zvolená FL překračuje poledník ±180°. Jednoduchý W/E obdélník by byl chybný."};
 return {south,north,west,east,level:top,
         features:candidates.flatMap(item=>item.layer.features.filter(f=>
           f.geometry&&["Polygon","MultiPolygon"].includes(f.geometry.type)))};
}
function currentExtent(){
 const values=["south","north","west","east"].map(key=>Number($("extent-"+key).value));
 if(values.some((v,i)=>!$("extent-"+["south","north","west","east"][i]).value.trim()||!Number.isFinite(v)))return null;
 const [south,north,west,east]=values;
 if(!(south>=-90&&north<=90&&south<north&&west>=-180&&east<=180&&west<east))return null;
 return {south,north,west,east};
}
function showExtentRectangle(){
 if(extentRectangle){map.removeLayer(extentRectangle);extentRectangle=null}
 const b=currentExtent();
 if(!b)return;
 extentRectangle=L.rectangle([[b.south,b.west],[b.north,b.east]],{
  color:"#ffbf69",weight:2,dashArray:"7,5",fillOpacity:.05,interactive:false
 }).addTo(map);
}
function updateExtentPreset(){
 const found=boundsFromHighestFlightLevel();
 if(!found||found.invalid){
  extentLevel=null;extentSelectedFeatures=[];
  $("extent-source").textContent=found?.invalid||
    "Žádná vypočtená FL s polygonovým krytím není načtena. Zadej rozsah ručně.";
  return;
 }
 extentLevel=found.level;
 extentSelectedFeatures=found.features;
 const spanLat=found.north-found.south,spanLon=found.east-found.west;
 // Small margin ensures that the exported bbox fully encloses the outer edge
 // after decimal rounding; avoid unbounded radius assumptions.
 const padLat=Math.max(.0001,spanLat*.01);
 const padLon=Math.max(.0001,spanLon*.01);
 const bounds={
  south:Math.max(-90,found.south-padLat),
  north:Math.min(90,found.north+padLat),
  west:Math.max(-180,found.west-padLon),
  east:Math.min(180,found.east+padLon)
 };
 for(const key of ["south","north","west","east"])
   $("extent-"+key).value=bounds[key].toFixed(6);
 $("extent-source").textContent="Automatický rozsah: nejvyšší FL "+
  found.level.toLocaleString("cs")+" ft · "+found.features.length+
  " polygonů, 1 % bezpečnostní okraj. Můžeš změnit souřadnice.";
 showExtentRectangle();
}
function downloadExtentGeoJSON(){
 const b=currentExtent();
 if(!b){notify("Oblast není platná. Zkontroluj S/N/W/E souřadnice.",true);return}
 const ring=[[b.west,b.south],[b.east,b.south],[b.east,b.north],
             [b.west,b.north],[b.west,b.south]];
 const data={type:"FeatureCollection",features:[{
  type:"Feature",
  properties:{name:"DEM download extent",highest_flight_level_ft:extentLevel,
   coordinate_reference_system:"EPSG:4326",
   south:b.south,north:b.north,west:b.west,east:b.east,
   note:"Bounding box includes outermost coverage polygon of highest available FL; not a DEM raster."},
  geometry:{type:"Polygon",coordinates:[ring]}
 }]};
 download("COVERAGEDIAGRAMS_DEM_extent_FL"+(extentLevel??"manual")+".geojson",
          new Blob([JSON.stringify(data)],{type:"application/geo+json"}));
}
function setRadarSite(lat,lon,origin){
 if(!Number.isFinite(lat)||!Number.isFinite(lon)||Math.abs(lat)>90||Math.abs(lon)>180)return false;
 radarCenter=[lat,lon];radarKnown=true;placingRadar=false;
 if(radarMarker&&map)map.removeLayer(radarMarker);
 if(map)radarMarker=L.circleMarker(radarCenter,{
   radius:8,color:"#ffbd6d",weight:2,fillColor:"#16547c",fillOpacity:1
  }).addTo(map);
 if(map)updateRange();
 $("range-center").textContent="Radar: "+lat.toFixed(6)+"° / "+lon.toFixed(6)+"° · "+origin;
 $("dem-set-radar").textContent="⌖ Změnit polohu radaru v mapě";
 return true;
}
function circleCandidate(ring){
 // Project a ring into local metric coordinates, then reject non-circular
 // coverage boundaries. Never use the center of an arbitrary KML polygon.
 if(!Array.isArray(ring)||ring.length<24)return null;
 const stride=Math.max(1,Math.floor(ring.length/720));
 const points=[];
 for(let i=0;i<ring.length;i+=stride){
  const p=ring[i];
  if(!Array.isArray(p)||!Number.isFinite(p[0])||!Number.isFinite(p[1]))continue;
  points.push(p);
 }
 if(points.length<24)return null;
 // Ignore the closing point; the fit uses uniquely distributed perimeter samples.
 if(points.length>24&&Math.abs(points[0][0]-points.at(-1)[0])<1e-9&&
     Math.abs(points[0][1]-points.at(-1)[1])<1e-9)points.pop();
 const lo=points.map(p=>p[0]),la=points.map(p=>p[1]);
 const midLat=(Math.max(...la)+Math.min(...la))/2;
 const midLon=(Math.max(...lo)+Math.min(...lo))/2;
 if(Math.max(...lo)-Math.min(...lo)>10||Math.abs(midLat)>78)return null;
 const sx=111320*Math.cos(midLat*Math.PI/180),sy=111195;
 if(sx<1)return null;
 const xy=points.map(p=>[(p[0]-midLon)*sx,(p[1]-midLat)*sy]);
 const x0=(Math.min(...xy.map(p=>p[0]))+Math.max(...xy.map(p=>p[0])))/2;
 const y0=(Math.min(...xy.map(p=>p[1]))+Math.max(...xy.map(p=>p[1])))/2;
 const radii=xy.map(p=>Math.hypot(p[0]-x0,p[1]-y0));
 const mean=radii.reduce((a,b)=>a+b,0)/radii.length;
 if(mean<100||mean>600000)return null;
 const rms=Math.sqrt(radii.reduce((sum,v)=>sum+(v-mean)**2,0)/radii.length);
 const angles=new Set(xy.map(p=>Math.floor((Math.atan2(p[1]-y0,p[0]-x0)+Math.PI)*18/Math.PI)));
 const coverage=angles.size/36;
 // Only near-complete concentric distance rings (not sectors, contours or rectangles).
 if(rms/mean>.035||coverage<.83)return null;
 const lat=midLat+y0/sy,lon=midLon+x0/sx;
 return {lat,lon,radius:mean,quality:rms/mean,coverage};
}
function detectRadarSiteFromLayers(){
 if(radarKnown)return true;
 // First prefer explicit site coordinates from a named radar point.
 for(const layer of layers.values()){
  for(const feature of layer.features){
   if(feature?.geometry?.type!=="Point")continue;
   const props=feature.properties||{};
   const name=[props.name,props.Name,props.title,props.type,props.category,layer.name].filter(Boolean).join(" ");
   if(!/(?:^|[^a-zA-Z])radar(?:[^a-zA-Z]|$)/i.test(name))continue;
   const coords=feature.geometry.coordinates;
   if(Array.isArray(coords)&&coords.length>=2&&
      setRadarSite(Number(coords[1]),Number(coords[0]),"radarový bod v KML"))return true;
  }
 }
 // Second choice: identify truly circular KML range rings and their shared site.
 // An irregular coverage polygon has no reliable radar center and is ignored.
 const circles=[];
 const read=geometry=>{
  if(!geometry)return;
  if(geometry.type==="GeometryCollection"){
   for(const g of geometry.geometries||[])read(g);
  }else if(geometry.type==="Polygon"){
   const candidate=circleCandidate(geometry.coordinates?.[0]);
   if(candidate)circles.push(candidate);
  }else if(geometry.type==="LineString"){
   const candidate=circleCandidate(geometry.coordinates);
   if(candidate)circles.push(candidate);
  }else if(geometry.type==="MultiPolygon"){
   for(const polygon of geometry.coordinates||[]){
    const candidate=circleCandidate(polygon[0]);
    if(candidate)circles.push(candidate);
   }
  }else if(geometry.type==="MultiLineString"){
   for(const ring of geometry.coordinates||[]){
    const candidate=circleCandidate(ring);
    if(candidate)circles.push(candidate);
   }
  }
 };
 for(const layer of layers.values())for(const feature of layer.features)read(feature.geometry);
 if(!circles.length)return false;
 // Prefer the common center of concentric rings. A single high-quality ring
 // is adequate; conflicting circles from unrelated features are not.
 circles.sort((a,b)=>a.quality-b.quality);
 let best=null;
 for(const pivot of circles.slice(0,Math.min(circles.length,30))){
  const matching=circles.filter(c=>
   Math.hypot((c.lon-pivot.lon)*111320*Math.cos(pivot.lat*Math.PI/180),
              (c.lat-pivot.lat)*111195)<Math.max(300,pivot.radius*.008));
  if(!best||matching.length>best.matching.length||
     matching.length===best.matching.length&&pivot.quality<best.pivot.quality)
    best={pivot,matching};
 }
 if(!best)return false;
 // Multiple rings of the same center are stronger evidence than one.
 const site=best.matching.reduce((a,c)=>({lat:a.lat+c.lat,lon:a.lon+c.lon}),{lat:0,lon:0});
 return setRadarSite(site.lat/best.matching.length,site.lon/best.matching.length,
                     best.matching.length+" soustředných kružnic KML");
}
function saveGeo(){
 const fs=[];for(const o of layers.values())if(o.style.show)fs.push(...o.features);
 download("COVERAGEDIAGRAMS_visible.geojson",new Blob([JSON.stringify({type:"FeatureCollection",features:fs})],{type:"application/geo+json"}))
}
function clearProfileExports(){
 lastProfile=null;
 $("profile-exports").hidden=true;
}
function setProfileExports(profile){
 lastProfile=profile;
 $("profile-exports").hidden=false;
}
function profileRayHeight(x,profile){
 const re=6371008.8*profile.k;
 const d=profile.ranges.at(-1);
 if(!Number.isFinite(d)||d<=0||!Number.isFinite(profile.targetAMSL)||!Number.isFinite(profile.antennaAMSL))return null;
 const phi=Math.atan2((re+profile.targetAMSL)*Math.cos(d/re)-(re+profile.antennaAMSL),
                      (re+profile.targetAMSL)*Math.sin(d/re));
 const height=(re+profile.antennaAMSL)*Math.cos(phi)/Math.cos(x/re+phi)-re;
 return Number.isFinite(height)?height:null;
}
function exportProfileCSV(){
 if(!lastProfile)return;
 const p=lastProfile;
 const rows=[
  ["# COVERAGEDIAGRAMS BOD / PROFIL"],
  ["# Mode",p.mode],
  ["# Result",p.verdict],
  ["# DEM source",p.source],
  ["# Radar latitude",p.radar[0]],
  ["# Radar longitude",p.radar[1]],
  ["# Target latitude",p.target[0]],
  ["# Target longitude",p.target[1]],
  ["# Target altitude (m AMSL)",p.targetAMSL],
  ["# Antenna altitude (m AMSL)",p.antennaAMSL],
  ["# Effective Earth factor k",p.k],
  ["# Target flight level (ft)",p.flightLevel??""],
  ["# Flight-level reference",p.reference??""],
  ["# Notes","A standalone DEM profile only establishes approximate LOS, not RF detection."],
  ["distance_m","latitude_deg","longitude_deg","terrain_m_amsl","ray_m_amsl","clearance_m"]
 ];
 p.ranges.forEach((d,i)=>{
  const ll=wgs84Destination(p.radar[0],p.radar[1],p.bearing,d);
  const terrain=p.terrain[i];
  const ray=profileRayHeight(d,p);
  rows.push([d,ll[0],ll[1],terrain??"",ray??"",
             Number.isFinite(terrain)&&Number.isFinite(ray)?ray-terrain:""]);
 });
 const csv="\uFEFF"+rows.map(row=>row.map(value=>{
   const v=String(value??"");
   return /[",\n\r]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;
 }).join(",")).join("\r\n");
 download("COVERAGEDIAGRAMS_point_profile.csv",
          new Blob([csv],{type:"text/csv;charset=utf-8"}));
}
function exportProfileSVG(){
 if(!lastProfile)return;
 const original=$("inspection-profile");
 const clone=original.cloneNode(true);
 clone.setAttribute("xmlns","http://www.w3.org/2000/svg");
 clone.setAttribute("width","1040");
 clone.setAttribute("height","368");
 const xml=new XMLSerializer().serializeToString(clone);
 download("COVERAGEDIAGRAMS_point_profile.svg",
          new Blob([xml],{type:"image/svg+xml;charset=utf-8"}));
}
function exportProfileGeoJSON(){
 if(!lastProfile)return;
 const p=lastProfile;
 const points=p.ranges.map((d,i)=>{
   const ll=wgs84Destination(p.radar[0],p.radar[1],p.bearing,d);
   return [ll[1],ll[0]];
 });
 const metadata={mode:p.mode,verdict:p.verdict,source:p.source,
  antenna_m_amsl:p.antennaAMSL,target_m_amsl:p.targetAMSL,
  reference:p.reference??"AMSL",flight_level_ft:p.flightLevel??null,
  k:p.k,comment:"Geometry/DEM analysis; no independent claim of radar detection."};
 const fc={type:"FeatureCollection",features:[
  {type:"Feature",properties:{name:"Radar → target profile",...metadata},
   geometry:{type:"LineString",coordinates:points}},
  {type:"Feature",properties:{name:"Radar",height_m_amsl:p.antennaAMSL},
   geometry:{type:"Point",coordinates:[p.radar[1],p.radar[0]]}},
  {type:"Feature",properties:{name:"Target",height_m_amsl:p.targetAMSL},
   geometry:{type:"Point",coordinates:[p.target[1],p.target[0]]}},
 ]};
 download("COVERAGEDIAGRAMS_point_profile.geojson",
          new Blob([JSON.stringify(fc)],{type:"application/geo+json"}));
}
async function loadDiagnostics(){
 if(!DATA.diagnostics){$("inspect").title="Vyber bod a automaticky načti profil DEM";return}
 try{
  const bytes=Uint8Array.from(atob(DATA.diagnostics),c=>c.charCodeAt(0));
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  grid=JSON.parse(await new Response(stream).text());
  $("native-level-row").hidden=false;
  $("dem-controls").hidden=true;
  const select=$("inspection-level");
  for(const ft of grid.levels){const option=document.createElement("option");option.value=ft;option.textContent=ft.toLocaleString("cs")+" ft "+grid.reference;select.add(option)}
  select.onchange=showInspection;
  $("inspect").title="Výběr bodu s diagnostikou výpočtu krytí";
 }catch(e){notify("Diagnostická síť se nepodařila otevřít: "+e.message,true)}
}
function radialAt(lat,lon){
 // WGS84 geodesic inverse (spherical initial estimate only to choose the nearest
 // native polar grid cell; the displayed point snaps to the WGS84 native sample).
 const p1=radarCenter[0]*Math.PI/180,p2=lat*Math.PI/180;
 const dl=(lon-radarCenter[1])*Math.PI/180,dp=p2-p1;
 const a=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
 const distance=6371008.8*2*Math.atan2(Math.sqrt(a),Math.sqrt(Math.max(0,1-a)));
 const bearing=(Math.atan2(Math.sin(dl)*Math.cos(p2),Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl))*180/Math.PI+360)%360;
 return {distance,bearing};
}
function rfInfoAtPoint(mode,distance_m,elevation_deg){
 if(mode==="PAR-NG"){
  return "RF · PAR-NG: dokumentovaný špičkový vysílací výkon 300 W (lineární polarizace) "+
         "nebo 600 W (eliptická polarizace), podle režimu.\n"+
         "Skutečný okamžitý režim/pulz není zaznamenán; přijatý výkon a dosažené SNR nelze "+
         "bez absolutního zisku, RCS, NF a šířky pásma spolehlivě určit.";
 }
 if(mode==="RL-2000"){
  return "RF · PSR: přesný vysílací výkon aktuální radarové konfigurace není zadán.\n"+
         "Výpočet je normalizovaný na referenční dosah; přijatý výkon v dBm "+
         "nelze bez Tx výkonu, absolutního zisku, RCS a přijímače určit.";
 }
 if(mode!=="SSR"||!grid.rfAssumptions)return "";
 const a=grid.rfAssumptions;
 // SSR is TWO one-way Friis paths, never a monostatic R^-4 radar echo.
 // The numbers are engineering assumptions in radar_core.SSR_ASSUMPTIONS.
 const gain=-Math.max(0,12*((elevation_deg-a.beam_peak_deg)/a.vertical_hpbw_deg)**2);
 const gainDb=Math.max(-80,gain);
 const received=(power,freq)=>power+a.ground_peak_gain_dbi+
    a.aircraft_gain_dbi+gainDb-a.losses_per_link_db-
    20*Math.log10(4*Math.PI*distance_m*freq*1e6/299792458);
 const up=received(a.interrogator_power_dbm,a.uplink_mhz);
 const down=received(a.transponder_power_dbm,a.downlink_mhz);
 const worst=Math.min(up-a.transponder_threshold_dbm-a.margin_per_link_db,
                      down-a.ground_threshold_dbm-a.margin_per_link_db);
 const watts=dbm=>Math.pow(10,(dbm-30)/10);
 return "RF · SSR (orientační předpoklady, nikoli kalibrovaný radar):\n"+
  "Pozemní vysílač: "+watts(a.interrogator_power_dbm).toFixed(0)+" W (1030 MHz)"+
  " · odpovídač: "+watts(a.transponder_power_dbm).toFixed(1)+" W (1090 MHz)\n"+
  "Odhad na letadle (uplink): "+up.toFixed(1)+" dBm"+
  " · na radaru (downlink): "+down.toFixed(1)+" dBm\n"+
  "Nejmenší rezerva vůči nastavenému prahu a rezervě: "+
  worst.toFixed(1)+" dB. Bez terénu, rušení, garblingu a selektivity.";
}
function showInspection(){
 clearProfileExports();
 if(!grid||!selectedPoint)return;
 const {distance,bearing}=radialAt(selectedPoint.lat,selectedPoint.lng);
 const delta=((bearing-grid.bearing+540)%360)-180;
 const inside=grid.radarMode!=="PAR-NG"||Math.abs(delta)<=15+1e-8;
 const select=(arr,x)=>arr.reduce((best,v,i)=>Math.abs(v-x)<Math.abs(arr[best]-x)?i:best,0);
 const i=select(grid.az,grid.radarMode==="PAR-NG"?grid.bearing+delta:bearing);
 const j=select(grid.distance,distance);
 if(!inside||distance>grid.distance.at(-1)||distance<0){
  $("inspection-result").textContent="MIMO VÝPOČETNÍ DOMÉNU · bod leží mimo sektor nebo dosah radaru.";
  $("inspection-profile").replaceChildren();$("inspection-details").textContent="Zvolený azimut: "+bearing.toFixed(2)+"° · vzdálenost: "+(distance/1000).toFixed(2)+" km";
  return;
 }
 const d=grid.distance[j],ft=Number($("inspection-level").value);
 const localGround=grid.terrain[i][j];
 const target=ft*.3048; // Flight levels are always ft AMSL.
 const samples=grid.terrain[i].slice(0,j+1),ranges=grid.distance.slice(0,j+1);
 const status=grid.status[String(ft)][i][j],ground=grid.terrain[i][j];
 const horizon=grid.lower[i][j],ceiling=grid.upper[i][j];
 const angle=Math.atan2((6371008.8*grid.k+target)*Math.cos(d/(6371008.8*grid.k))-(6371008.8*grid.k+grid.antenna),
   (6371008.8*grid.k+target)*Math.sin(d/(6371008.8*grid.k)))*180/Math.PI;
 let maxAngle=-Infinity,blocker=-1;
 for(let n=0;n<samples.length;n++){
  const z=samples[n],x=ranges[n];if(!Number.isFinite(z))continue;
  const q=Math.atan2((6371008.8*grid.k+z)*Math.cos(x/(6371008.8*grid.k))-(6371008.8*grid.k+grid.antenna),
   (6371008.8*grid.k+z)*Math.sin(x/(6371008.8*grid.k)))*180/Math.PI;
  if(q>maxAngle){maxAngle=q;blocker=n}
 }
 let causes=[];
 if(status===2)causes.push("Neúplná data DEM na trase – neznámé krytí");
 else if(status===0){
  if(target<ground)causes.push("Cíl pod úrovní místního terénu");
  if(target<horizon-1e-5)causes.push("Terénní stín / překážka");
  if(angle<grid.minElev-1e-5||angle>grid.maxElev+1e-5)causes.push("Mimo elevační rozsah");
  if(!causes.length)causes.push("Dosahový limit anténního diagramu / RF bilance / zadaná překážka");
 }
 const textStatus=status===2?"NEZNÁMÉ":status===1?"KRYTÝ":"NEKRYTÝ";
 const native=wgs84Destination(radarCenter[0],radarCenter[1],grid.az[i],d);
 if(inspectionLine)map.removeLayer(inspectionLine);
 if(inspectionMarker)map.removeLayer(inspectionMarker);
 inspectionLine=L.polyline([radarCenter,native],{color:"#fcbd67",weight:3,dashArray:"6,5",interactive:false}).addTo(map);
 inspectionMarker=L.circleMarker(native,{radius:7,color:"#fff",fillColor:status===1?"#1acb92":status===0?"#fa646d":"#e5ad54",fillOpacity:1,weight:2}).addTo(map);
 $("inspection").hidden=false;
 $("inspection-result").textContent=textStatus+" · "+ft+" ft "+grid.reference+(causes.length?"\n"+causes.join(" · "):"");
 $("inspection-details").textContent=
  "Kliknutý bod: "+selectedPoint.lat.toFixed(6)+"°, "+selectedPoint.lng.toFixed(6)+"°\n"+
  "Výpočetní vzorek: "+native[0].toFixed(6)+"°, "+native[1].toFixed(6)+"°\n"+
  "Azimut: "+(grid.az[i]%360+360)%360+"° · horizontální vzdálenost: "+(d/1000).toFixed(3)+" km\n"+
  "Výška antény: "+grid.antenna.toFixed(1)+" m AMSL · cíl: "+(Number.isFinite(target)?target.toFixed(1):"N/A")+" m AMSL\n"+
  "Terén v cíli: "+(Number.isFinite(ground)?ground.toFixed(1):"N/A")+" m AMSL\n"+
  "Minimální potřebná výška pro LOS: "+(Number.isFinite(horizon)?horizon.toFixed(1):"N/A")+" m AMSL\n"+
  "Maximální geometrická výška: "+(Number.isFinite(ceiling)?ceiling.toFixed(1):"N/A")+" m AMSL\n"+
  "Elevace cíle: "+(Number.isFinite(angle)?angle.toFixed(3):"N/A")+"° · překážkový horizont: "+(Number.isFinite(maxAngle)?maxAngle.toFixed(3):"N/A")+"°\n"+
  "Limitní terén: "+(blocker>=0?(ranges[blocker]/1000).toFixed(3)+" km / "+samples[blocker].toFixed(1)+" m AMSL":"N/A")+"\n"+
  "Model Země: R = 6371008,8 m × k "+grid.k+" · krok azimutu a vzdálenosti je diskrétní.\n"+
  (grid.radarMode==="PAR-NG"?"Sektorový útlum PAR: "+(grid.sectorEdgeLoss*(Math.min(1,Math.abs(((grid.az[i]-grid.bearing+540)%360)-180)/15)**2)).toFixed(3)+" dB (kvadraticky, −"+grid.sectorEdgeLoss.toFixed(1)+" dB na okrajích).\\n":"")+
  "Závěr pochází přímo z masky krytí EDITORU; profil z původních vzorků DEM.\n\n"+
  rfInfoAtPoint(grid.radarMode,Math.sqrt(d*d+(target-grid.antenna)*(target-grid.antenna)),angle);
 if(Number.isFinite(target))drawProfile(ranges,samples,d,target);
 else $("inspection-profile").replaceChildren();
 setProfileExports({
  mode:"EDITOR_NATIVE",source:"Original EDITOR DEM / coverage grid",
  verdict:textStatus,radar:[...radarCenter],
  target:[native[0],native[1]],bearing:grid.az[i],
  ranges:[...ranges],terrain:[...samples],
  targetAMSL:Number.isFinite(target)?target:null,
  antennaAMSL:grid.antenna,k:grid.k,
  flightLevel:ft,reference:grid.reference
 });
}
function drawProfile(ranges,terrain,d,target){
 const svg=$("inspection-profile");svg.replaceChildren();
 const finite=terrain.filter(Number.isFinite);
 if(!finite.length)return;
 const min=Math.min(...finite,grid.antenna,target)-40,max=Math.max(...finite,grid.antenna,target)+40;
 const x=v=>26+v/d*475,y=v=>166-(v-min)/(max-min)*144;
 function poly(points,color,width,dash=""){const e=document.createElementNS("http://www.w3.org/2000/svg","polyline");
 e.setAttribute("points",points.map(p=>p.map(v=>v.toFixed(1)).join(",")).join(" "));e.setAttribute("fill","none");e.setAttribute("stroke",color);e.setAttribute("stroke-width",width);
 if(dash)e.setAttribute("stroke-dasharray",dash);svg.append(e)}
 let segment=[];
 terrain.forEach((z,i)=>{if(Number.isFinite(z))segment.push([x(ranges[i]),y(z)]);
 else if(segment.length){poly(segment,"#63d9b0",2);segment=[]}});
 if(segment.length)poly(segment,"#63d9b0",2);
 const re=6371008.8*grid.k;
 const angle=Math.atan2((re+target)*Math.cos(d/re)-(re+grid.antenna),(re+target)*Math.sin(d/re));
 // Exact same effective-Earth apparent angle and inverse height-at-angle as radar_core.
 const ray=ranges.map(v=>[x(v),y((re+grid.antenna)*Math.cos(angle)/Math.cos(v/re+angle)-re)]);
 poly([[x(0),y(grid.antenna)],...ray],"#ffbc63",2,"5,4");
 const txt=document.createElementNS("http://www.w3.org/2000/svg","text");
 txt.setAttribute("x",30);txt.setAttribute("y",14);txt.setAttribute("fill","#cde6f6");txt.setAttribute("font-size","11");
 txt.textContent="DEM (zelená) · LOS paprsek (oranžová) · "+(d/1000).toFixed(2)+" km";svg.append(txt)
}
async function downloadDemProfile(target, request){
 const params=radialAt(target.lat,target.lng);
 const distance=params.distance, bearing=params.bearing;
 if(distance<20)throw Error("Bod musí být alespoň 20 m od radaru.");
 if(distance>500000)throw Error("Pro DEM profil je podporována vzdálenost nejvýše 500 km.");
 // Copernicus 90m DEM; sample at >=120m spacing and max 400 points.
 const n=Math.min(400,Math.max(2,Math.ceil(distance/150)+1));
 const ranges=Array.from({length:n},(_,i)=>distance*i/(n-1));
 const positions=ranges.map(d=>wgs84Destination(radarCenter[0],radarCenter[1],bearing,d));
 const cacheKey=[...radarCenter,target.lat,target.lng].map(v=>v.toFixed(5)).join(":");
 if(demCache.has(cacheKey))return demCache.get(cacheKey);
 if(demController)demController.abort();
 demController=new AbortController();
 const heights=[];
 for(let offset=0;offset<n;offset+=100){
  if(request!==demRequest)throw Error("Analýza byla nahrazena novým bodem.");
  const group=positions.slice(offset,offset+100);
  const url="https://api.open-meteo.com/v1/elevation?latitude="+
    group.map(p=>p[0].toFixed(6)).join(",")+"&longitude="+
    group.map(p=>p[1].toFixed(6)).join(",");
  const response=await fetch(url,{signal:demController.signal,cache:"default"});
  if(!response.ok)throw Error("DEM API vrátilo HTTP "+response.status);
  const data=await response.json();
  if(!Array.isArray(data.elevation)||data.elevation.length!==group.length)
    throw Error("API nevrátilo kompletní výškový profil.");
  heights.push(...data.elevation.map(v=>typeof v==="number"&&Number.isFinite(v)?v:null));
  if(request===demRequest)$("inspection-result").textContent=
    "Načítám terénní model… "+heights.length+" / "+n+" bodů";
 }
 const result={ranges,heights,bearing,distance,
               resolution:distance/(n-1),source:"Copernicus GLO-90 / Open-Meteo"};
 demCache.set(cacheKey,result);
 if(demCache.size>12)demCache.delete(demCache.keys().next().value);
 return result;
}
function drawStandaloneProfile(ranges,terrain,targetAMSL,antennaAMSL,k){
 const svg=$("inspection-profile");svg.replaceChildren();
 const valid=terrain.filter(Number.isFinite);
 if(!valid.length)return;
 const dist=ranges.at(-1),re=6371008.8*k;
 const phi=Math.atan2((re+targetAMSL)*Math.cos(dist/re)-(re+antennaAMSL),
                      (re+targetAMSL)*Math.sin(dist/re));
 const rayHeight=x=>(re+antennaAMSL)*Math.cos(phi)/Math.cos(x/re+phi)-re;
 const values=[...valid,targetAMSL,antennaAMSL];
 const ys=ranges.map(rayHeight).filter(Number.isFinite);
 values.push(...ys);
 const min=Math.min(...values)-30,max=Math.max(...values)+30;
 const sx=x=>25+(x/dist)*475,sy=z=>164-(z-min)/(max-min)*138;
 function line(coords,color,dashed=false){
  const el=document.createElementNS("http://www.w3.org/2000/svg","polyline");
  el.setAttribute("points",coords.map(p=>p.map(x=>x.toFixed(1)).join(",")).join(" "));
  el.setAttribute("stroke",color);el.setAttribute("fill","none");
  el.setAttribute("stroke-width","2.2");
  if(dashed)el.setAttribute("stroke-dasharray","6,4");
  svg.append(el);
 }
 let part=[];
 terrain.forEach((z,i)=>{if(Number.isFinite(z))part.push([sx(ranges[i]),sy(z)]);
   else if(part.length){line(part,"#5bdeb2");part=[]}});
 if(part.length)line(part,"#5bdeb2");
 line(ranges.map(x=>[sx(x),sy(rayHeight(x))]),"#ffc16e",true);
 const caption=document.createElementNS("http://www.w3.org/2000/svg","text");
 caption.setAttribute("x","25");caption.setAttribute("y","14");
 caption.setAttribute("fill","#d4ebff");caption.setAttribute("font-size","11");
 caption.textContent="Zelená: DEM · Oranžová: přímá viditelnost (LOS)";
 svg.append(caption);
}
async function showStandaloneInspection(){
 clearProfileExports();
 if(!selectedPoint)return;
 if(!radarKnown){$("inspection-result").textContent="Nejprve nastav pozici radaru kliknutím do mapy.";
   $("inspection-details").textContent="Bez polohy radaru nelze určit trasu ani LOS.";return;}
 const request=++demRequest;
 $("inspection").hidden=false;
 $("inspection-result").textContent="Načítám DEM pro trasu radar → bod…";
 $("inspection-details").textContent="Výškový profil se stahuje automaticky. Bez editorového výpočtu nelze určit RF krytí.";
 $("inspection-profile").replaceChildren();
 if(inspectionLine)map.removeLayer(inspectionLine);
 if(inspectionMarker)map.removeLayer(inspectionMarker);
 inspectionLine=L.polyline([radarCenter,selectedPoint],{color:"#ffbd6d",weight:3,dashArray:"7,5",interactive:false}).addTo(map);
 inspectionMarker=L.circleMarker(selectedPoint,{radius:7,color:"#fff",fillColor:"#f7b45b",
                                               fillOpacity:1,weight:2}).addTo(map);
 try{
  const profile=await downloadDemProfile(selectedPoint,request);
  if(request!==demRequest)return;
  const {ranges,heights,distance,bearing,resolution}=profile;
  const agl=Number($("dem-antenna").value),ft=Number($("dem-target").value),k=Number($("dem-k").value);
  if(!Number.isFinite(agl)||agl<=0||!Number.isFinite(ft)||!Number.isFinite(k)||k<.5||k>3)
    throw Error("Zadej platnou výšku antény, hladinu a faktor k.");
  const site=heights[0],target=ft*.3048;
  if(!Number.isFinite(site)||heights.some(h=>!Number.isFinite(h))){
    $("inspection-result").textContent="NEZNÁMÉ LOS · DEM neobsahuje všechna potřebná data.";
    $("inspection-details").textContent="Nevyplněná místa v DEM nesmí být vyhodnocena jako viditelná.";
    drawStandaloneProfile(ranges,heights,target,Number.isFinite(site)?site+agl:target,k);
    return;
  }
  const antenna=site+agl,re=6371008.8*k;
  const angle=Math.atan2((re+target)*Math.cos(distance/re)-(re+antenna),
                         (re+target)*Math.sin(distance/re));
  let limit=Infinity,blocker=-1;
  for(let i=1;i<ranges.length-1;i++){
   const x=ranges[i];
   const ray=(re+antenna)*Math.cos(angle)/Math.cos(x/re+angle)-re;
   const clearance=ray-heights[i];
   if(clearance<limit){limit=clearance;blocker=i}
  }
  const visible=(limit>=0&&target>=heights.at(-1));
  $("inspection-result").textContent=(visible?"LOS VOLNÁ":"LOS BLOKOVANÁ")+
    " · geometrie z automaticky staženého DEM (nikoliv RF krytí)";
  $("inspection-details").textContent=
    "Zdroj: Copernicus DEM GLO-90 / Open-Meteo · nejedná se o radarovou detekční analýzu.\n"+
    "Radar: "+radarCenter.map(x=>x.toFixed(6)+"°").join(", ")+" · "+site.toFixed(1)+" m AMSL\n"+
    "Bod: "+selectedPoint.lat.toFixed(6)+"°, "+selectedPoint.lng.toFixed(6)+"°\n"+
    "Azimut: "+bearing.toFixed(3)+"° · vzdálenost: "+(distance/1000).toFixed(3)+" km\n"+
    "Vzorkování trasy: "+ranges.length+" bodů / "+resolution.toFixed(0)+" m mezi body (zdrojový DEM 90 m)\n"+
    "Anténa: "+antenna.toFixed(1)+" m AMSL · cíl: "+target.toFixed(1)+" m AMSL\n"+
    "Terén cíle: "+heights.at(-1).toFixed(1)+" m AMSL · elevace: "+(angle*180/Math.PI).toFixed(3)+"°\n"+
    "Minimální rezerva nad DEM: "+(Number.isFinite(limit)?limit.toFixed(1):"N/A")+" m"+
    (blocker>=0?" v "+(ranges[blocker]/1000).toFixed(2)+" km":"")+
    "\nZakřivení: Rz × k = "+(re/1000).toFixed(1)+
    " km. Není zahrnuta Fresnelova zóna, objekty ani RCS/SNR.\n"+
    "RF: Bez konfigurace radaru a jeho kalibrovaných hodnot nelze vypočítat "+
    "vysílací režim ani přijatý výkon.";
  drawStandaloneProfile(ranges,heights,target,antenna,k);
  setProfileExports({
   mode:"STANDALONE_DEM_LOS",source:profile.source,
   verdict:visible?"LOS VOLNÁ":"LOS BLOKOVANÁ",
   radar:[...radarCenter],target:[selectedPoint.lat,selectedPoint.lng],
   bearing,ranges:[...ranges],terrain:[...heights],
   targetAMSL:target,antennaAMSL:antenna,k,flightLevel:ft,reference:"AMSL"
  });
  status("DEM načten: "+ranges.length+" bodů · "+(visible?"LOS volná":"LOS blokovaná"));
 }catch(error){
  if(request!==demRequest)return;
  $("inspection-result").textContent="DEM SE NEPODAŘILO NAČÍST";
  $("inspection-details").textContent=error.message+
    "\nZkontroluj připojení a dostupnost veřejného API. Krytí není bez DEM určitelné.";
  status("Chyba DEM: "+error.message);
 }
}
function setup(){
 if(!window.L){status("Leaflet se nepodařilo načíst. Zkontroluj připojení nebo blokování CDN.");return}
 map=L.map("map",{center:radarCenter,zoom:7,preferCanvas:true,zoomControl:false,
   zoomAnimation:false,fadeAnimation:false,attributionControl:true});
 vectorRenderer=L.canvas({padding:.5});
 L.control.zoom({position:"topright"}).addTo(map);L.control.scale({position:"bottomright",imperial:false}).addTo(map);
 selectBase("hillshade");
 for(const [name,features] of Object.entries(DATA.layers||{}))addLayer(name,features,DATA.styles?.[name],false);
 refreshList();syncAll();fitAll();updateExtentPreset();
 if(radarKnown)setRadarSite(radarCenter[0],radarCenter[1],"EDITOR");
 else detectRadarSiteFromLayers();
 loadDiagnostics();
 $("inspect").onclick=()=>{
  inspectEnabled=!inspectEnabled;$("inspect").setAttribute("aria-pressed",String(inspectEnabled));
  $("inspect").classList.toggle("primary",inspectEnabled);
  map.getContainer().style.cursor=inspectEnabled?"crosshair":"";
  if(inspectEnabled){
    $("inspection").hidden=false;
    if(!grid&&!radarKnown){
      placingRadar=true;
      $("inspection-result").textContent="Nejprve klikni do mapy na polohu radaru. Poté klikni na analyzovaný bod.";
    }else{
      $("inspection-result").textContent="Klikni do mapy; terén se načte automaticky, pokud chybí výpočet z EDITORU.";
    }
  }else{placingRadar=false}
 };
 map.on("click",e=>{
  if(placingRadar){
    setRadarSite(e.latlng.lat,e.latlng.lng,"ručně vybraná poloha");
    $("inspection-result").textContent="Poloha radaru nastavena. Klikni na cíl.";
    return;
  }
  if(!inspectEnabled)return;
  selectedPoint=e.latlng;
  if(grid)showInspection();
  else showStandaloneInspection();
 });
 $("dem-set-radar").onclick=()=>{
  placingRadar=true;inspectEnabled=true;
  $("inspection").hidden=false;
  $("inspect").classList.add("primary");
  $("inspection-result").textContent="Klikni do mapy na polohu radaru.";
 };
 for(const id of ["dem-antenna","dem-target","dem-k"]){
  $(id).addEventListener("change",()=>{if(selectedPoint&&!grid)showStandaloneInspection()});
 }
 $("profile-csv").onclick=exportProfileCSV;
 $("profile-svg").onclick=exportProfileSVG;
 $("profile-geo").onclick=exportProfileGeoJSON;
 $("inspection-close").onclick=()=>{$("inspection").hidden=true;inspectEnabled=false;$("inspect").classList.remove("primary");$("inspect").setAttribute("aria-pressed","false");map.getContainer().style.cursor=""};
 $("print-studio").onclick=()=>window.open(DATA.studioUrl,"_blank","noopener");
 $("panel-toggle").onclick=()=>{const hidden=$("panel").classList.toggle("hidden");$("panel-toggle").setAttribute("aria-expanded",String(!hidden));map.invalidateSize()};
 $("close").onclick=()=>{$("panel").classList.add("hidden");$("panel-toggle").setAttribute("aria-expanded","false")};
 $("fit").onclick=fitAll;
 $("quick-open").onclick=$("load").onclick=()=>{$("file").value="";$("file").click()};
 $("file").onchange=e=>importFiles(e.target.files);
 document.querySelectorAll("[data-tab]").forEach(btn=>btn.onclick=()=>{
   document.querySelectorAll("[data-tab]").forEach(b=>b.classList.toggle("active",b===btn));
   document.querySelectorAll(".section").forEach(s=>s.hidden=s.id!=="tab-"+btn.dataset.tab)
 });
 $("search").oninput=refreshList;
 $("all").onclick=()=>{for(const o of layers.values())o.style.show=true;refreshList();syncAll()};
 $("none").onclick=()=>{for(const o of layers.values())o.style.show=false;refreshList();syncAll()};
 $("invert").onclick=()=>{for(const o of layers.values())o.style.show=!o.style.show;refreshList();syncAll()};
 $("clear").onclick=()=>{if(!confirm("Odstranit všechny načtené vrstvy?"))return;resetLayers();refreshList();refreshLegend();updateExtentPreset();notify("Vrstvy odstraněny")};
 $("base").onchange=e=>selectBase(e.target.value);
 $("labels").onchange=e=>{setting.labels=e.target.checked;for(const o of layers.values())if(o.geo)o.geo.eachLayer(l=>{
   if(l.getTooltip())l.getTooltip().options.opacity=setting.labels?1:0
 })};
 $("legend").onchange=e=>{setting.legend=e.target.checked;refreshLegend()};
 $("range-on").onchange=e=>{setting.range=e.target.checked;updateRange()};
 $("range").oninput=updateRange;
 $("extent-auto").onclick=updateExtentPreset;
 $("extent-fit").onclick=()=>{showExtentRectangle();const b=currentExtent();if(b)map.fitBounds([[b.south,b.west],[b.north,b.east]],{padding:[45,45]});};
 $("extent-export").onclick=downloadExtentGeoJSON;
 for(const key of ["south","north","west","east"])
   $("extent-"+key).addEventListener("change",()=>{extentLevel=null;showExtentRectangle()});
 $("save-geo").onclick=saveGeo;$("save-project").onclick=()=>saveCDView().catch(e=>notify(e.message,true));
 let dragDepth=0;
 document.addEventListener("dragenter",e=>{e.preventDefault();dragDepth++;$("drop").classList.add("on")});
 document.addEventListener("dragleave",e=>{e.preventDefault();if(--dragDepth<=0){dragDepth=0;$("drop").classList.remove("on")}});
 document.addEventListener("dragover",e=>e.preventDefault());
 document.addEventListener("drop",e=>{e.preventDefault();dragDepth=0;$("drop").classList.remove("on");importFiles(e.dataTransfer.files)});
 window.addEventListener("resize",()=>map.invalidateSize({pan:false,animate:false}));
 status(layers.size+" vrstev · mapový pracovní prostor připraven");
}
setup();
</script></body></html>"""
