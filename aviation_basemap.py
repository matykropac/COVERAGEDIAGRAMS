"""Native aeronautical OpenAIP raster layer for Folium traffic maps.

OpenAIP requires a personal API key. This implementation uses the official tile
endpoint, not adsb.aero's private proxy. The tile URL is delivered to the user's
browser as with other Leaflet providers; use a dedicated limited-scope key.
"""
from urllib.parse import quote

import folium
import streamlit as st

ATTRIBUTION = 'Aeronautical data © <a href="https://www.openaip.net/">OpenAIP</a>'
URL = "https://api.tiles.openaip.net/api/data/openaip/{z}/{x}/{y}.png?apiKey={key}"


def active_key():
    return str(st.session_state.get("traffic_openaip_key", "")).strip()


def controls():
    """Shared setting for all PROVOZ map modes."""
    with st.expander("LETECKÉ MAPOVÉ VRSTVY · OpenAIP", expanded=False):
        st.checkbox("Letecká mapa OpenAIP", value=True, key="traffic_openaip_enabled")
        st.text_input(
            "Vlastní OpenAIP API klíč",
            type="password",
            key="traffic_openaip_key",
            help="OpenAIP vyžaduje API klíč. Odesílá se poskytovateli "
                 "v URL mapových dlaždic a je viditelný v síťových požadavcích prohlížeče.")
        if not active_key():
            st.caption("Pro zobrazení OpenAIP zadej svůj klíč z openaip.net. "
                       "Běžná mapová vrstva a radarové krytí fungují i bez něj.")
        st.caption("Vrstva je přímo součástí mapy, lze ji přepínat v nabídce vrstev. "
                   "Pouze analytické použití, nikoli certifikovaná navigační mapa.")


def configured_key():
    if not st.session_state.get("traffic_openaip_enabled", True):
        return None
    return active_key() or None


def add_to_map(map_obj, key, *, show=True):
    if not key:
        return False
    folium.TileLayer(
        tiles=URL.format(z="{z}", x="{x}", y="{y}", key=quote(key, safe="")),
        name="LETECKÁ MAPA · OpenAIP",
        attr=ATTRIBUTION,
        overlay=True,
        control=True,
        show=show,
        max_zoom=18,
        opacity=0.9,
    ).add_to(map_obj)
    return True
