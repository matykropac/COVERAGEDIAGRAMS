"""Persistent Leaflet v2 component: one map instance, incremental layer updates.

Browser interactions are explicit triggers; panning and zooming stay local to JS.
Never regenerate the map on a radar-height or ADS-B update.
"""
from pathlib import Path
import streamlit as st

_DIR=Path(__file__).resolve().parent
_HTML='''<div id="cd-persistent-map" role="application" aria-label="Radar coverage map"></div>
<section id="cd-terrain-panel" aria-label="Terénní profil vybraného bodu" hidden>
  <div class="cd-terrain-head">
    <div><strong>TERÉNNÍ PROFIL</strong><span id="cd-terrain-summary">Klikni do mapy a vyber bod.</span></div>
    <button id="cd-terrain-close" type="button" aria-label="Zavřít profil">×</button>
  </div>
  <div class="cd-terrain-plot"><canvas id="cd-terrain-canvas" aria-label="Graf terénního profilu a spodní hranice radarového krytí"></canvas></div>
  <div class="cd-terrain-legend"><span><i class="cd-terrain-swatch"></i>Terén AMSL</span><span><i class="cd-lower-swatch"></i>Spodní hranice krytí</span><span><i class="cd-selected-swatch"></i>Vybraný bod</span></div>
</section>
<div id="cd-map-status" aria-live="polite"></div>'''
_CSS="""
#cd-persistent-map { width:100%;height:calc(100dvh - 68px);min-height:480px;
    border:1px solid #cfdae6;border-radius:8px;overflow:hidden;background:#e5edf5}
#cd-map-status {position:absolute;right:22px;bottom:22px;z-index:900;
    padding:5px 9px;border-radius:5px;background:#fffdeb;color:#38516b;
    font:11px system-ui;box-shadow:0 1px 8px #17263824;display:none}
 
#cd-terrain-panel {position:relative;margin-top:8px;padding:9px 14px 10px;
   border:1px solid #cddae7;border-radius:9px;background:#fff;color:#263d54;
   box-shadow:0 2px 10px #1b365011;font:12px system-ui}
#cd-terrain-panel[hidden]{display:none!important}
.cd-terrain-head{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-bottom:6px}
.cd-terrain-head>div{display:flex;align-items:baseline;gap:13px;min-width:0;flex-wrap:wrap}
.cd-terrain-head strong{font-size:11px;letter-spacing:.09em;color:#2062aa;white-space:nowrap}
#cd-terrain-summary{font-size:12px;color:#4b6077}
#cd-terrain-close{border:1px solid #dbe4eb;background:#f4f7fb;color:#476178;
   width:26px;height:25px;cursor:pointer;border-radius:5px;font:20px/21px system-ui}
.cd-terrain-plot{width:100%;height:150px;overflow:hidden}
#cd-terrain-canvas{width:100%;height:150px;display:block}
.cd-terrain-legend{display:flex;justify-content:flex-end;gap:16px;margin-top:3px;
   color:#60758a;font-size:10px;flex-wrap:wrap}
.cd-terrain-legend span{display:flex;align-items:center;gap:5px}
.cd-terrain-legend i{width:16px;height:3px;display:inline-block;background:#139db2}
.cd-terrain-legend .cd-lower-swatch{background:#dd8841}
.cd-terrain-legend .cd-selected-swatch{background:#e34c57}
#cd-persistent-map .leaflet-control-layers{border:1px solid #bccbd9;box-shadow:0 2px 9px #202c3820}
@media(max-width:700px){#cd-persistent-map{height:calc(100dvh - 92px);min-height:420px}}
"""
# Read the trusted JS module only from the application repository.
_JS=(_DIR/"assets"/"persistent_leaflet.js").read_text(encoding="utf-8")
_COMPONENT=st.components.v2.component(
    name="coverage_persistent_leaflet_v1",html=_HTML,css=_CSS,js=_JS,isolate_styles=False,
)

def show_persistent_map(payload):
    """Return one-time radar/polygon action; the map itself survives widget reruns."""
    result=_COMPONENT(
        key="coverage_main_leaflet",
        data=payload,
        on_action_change=lambda: None,
        default={},
    )
    return getattr(result,"action",None)
