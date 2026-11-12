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
#cd-persistent-map { width:100%;height:100dvh;min-height:0;
    border:0;border-radius:0;overflow:hidden;background:#e5edf5}
#cd-map-status {position:absolute;right:22px;bottom:22px;z-index:900;
    padding:5px 9px;border-radius:5px;background:#fffdeb;color:#38516b;
    font:11px system-ui;box-shadow:0 1px 8px #17263824;display:none}
 
.cd-profile-active #cd-persistent-map{height:100dvh;min-height:0}
#cd-terrain-panel {position:absolute;left:20px;bottom:26px;z-index:1050;
   width:min(690px,calc(100vw - 40px));max-height:45dvh;overflow:auto;
   margin:0;padding:9px 14px 10px;border:1px solid #395b76;border-radius:12px;
   background:#101e30f2;color:#e3edf9;box-shadow:0 12px 38px #02071188;font:12px system-ui}
#cd-terrain-panel[hidden]{display:none!important}
.cd-terrain-head{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-bottom:6px}
.cd-terrain-head>div{display:flex;align-items:baseline;gap:13px;min-width:0;flex-wrap:wrap}
.cd-terrain-head strong{font-size:11px;letter-spacing:.09em;color:#78d2fc;white-space:nowrap}
#cd-terrain-summary{font-size:12px;color:#c6d7e6}
#cd-terrain-close{border:1px solid #dbe4eb;background:#f4f7fb;color:#476178;
   width:26px;height:25px;cursor:pointer;border-radius:5px;font:20px/21px system-ui}
.cd-terrain-plot{width:100%;height:150px;overflow:hidden}
#cd-terrain-canvas{width:100%;height:150px;display:block}
.cd-terrain-legend{display:flex;justify-content:flex-end;gap:16px;margin-top:3px;
   color:#c1d4e3;font-size:10px;flex-wrap:wrap}
.cd-terrain-legend span{display:flex;align-items:center;gap:5px}
.cd-terrain-legend i{width:16px;height:3px;display:inline-block;background:#139db2}
.cd-terrain-legend .cd-lower-swatch{background:#dd8841}
.cd-terrain-legend .cd-selected-swatch{background:#e34c57}
/* DAY/NIGHT is a visual filter on persistent tiles, never a reload. */
#cd-persistent-map{transition:background-color .2s ease}
#cd-persistent-map.cd-night{background:#090e13}
#cd-persistent-map.cd-night img.cd-basemap-tile{
  filter:invert(1) hue-rotate(180deg) brightness(.73) contrast(1.18) saturate(.58)
}
#cd-persistent-map.cd-night img.cd-satellite-tile{
  filter:brightness(.55) contrast(1.16) saturate(.75)
}
#cd-persistent-map.cd-night img.cd-aip-tile{
  filter:brightness(.84) saturate(.95)
}
#cd-persistent-map.cd-night .leaflet-control-zoom a,
#cd-persistent-map.cd-night .leaflet-control-layers,
#cd-persistent-map.cd-night .leaflet-control-attribution{
  background:#15202c!important;color:#d7e4f0!important;
  border-color:#344659!important
}
#cd-persistent-map.cd-night .leaflet-control-attribution a{color:#9cc9f6!important}
#cd-persistent-map.cd-night .leaflet-control-layers label{color:#d7e4f0!important}
#cd-persistent-map.cd-night .leaflet-popup-content-wrapper,
#cd-persistent-map.cd-night .leaflet-popup-tip{background:#172331;color:#dce7f2}
#cd-persistent-map .leaflet-control-layers{border:1px solid #bccbd9;box-shadow:0 2px 9px #202c3820}
@media(max-width:700px){#cd-persistent-map{height:100dvh;min-height:0}
 #cd-terrain-panel{left:10px;bottom:12px;width:calc(100vw - 20px);max-height:42dvh}}
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
