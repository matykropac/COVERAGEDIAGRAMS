"""Persistent Leaflet v2 component: one map instance, incremental layer updates.

Browser interactions are explicit triggers; panning and zooming stay local to JS.
Never regenerate the map on a radar-height or ADS-B update.
"""
from pathlib import Path
import streamlit as st

_DIR=Path(__file__).resolve().parent
_HTML='<div id="cd-persistent-map" role="application" aria-label="Radar coverage map"></div><div id="cd-map-status" aria-live="polite"></div>'
_CSS="""
#cd-persistent-map { width:100%;height:calc(100dvh - 68px);min-height:530px;
    border:1px solid #cfdae6;border-radius:8px;overflow:hidden;background:#e5edf5}
#cd-map-status {position:absolute;right:22px;bottom:22px;z-index:900;
    padding:5px 9px;border-radius:5px;background:#fffdeb;color:#38516b;
    font:11px system-ui;box-shadow:0 1px 8px #17263824;display:none}
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
