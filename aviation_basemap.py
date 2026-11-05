"""Shared OpenAIP aviation chart overlay for COVERAGEDIAGRAMS Folium maps.

Set OPENAIP_API_KEY in Streamlit secrets or the server environment.
Never commit API credentials. Raster requests run in the user's browser;
the key appears in browser network requests. Use only a key permitted
for client-side map tiles, ideally domain-restricted by the provider.
"""
import os
from urllib.parse import quote

import folium

ATTRIBUTION = 'Aeronautical data © <a href="https://www.openaip.net/">OpenAIP</a>'
URL = "https://api.tiles.openaip.net/api/data/openaip/{z}/{x}/{y}.png?apiKey={key}"


def configured_key():
    key = os.environ.get("OPENAIP_API_KEY", "").strip()
    if key:
        return key
    try:
        import streamlit as st
        return str(st.secrets.get("OPENAIP_API_KEY", "")).strip() or None
    except (FileNotFoundError, KeyError, OSError):
        return None


def controls():
    """Informational status only; map overlay is enabled by default globally."""
    import streamlit as st
    if configured_key():
        st.caption("Letecká mapa OpenAIP je automaticky dostupná ve všech interaktivních mapách.")
    else:
        st.caption("OpenAIP: nastav OPENAIP_API_KEY v zabezpečeném nastavení aplikace. "
                   "Do té doby se používají standardní mapové podklady.")


def add_to_map(map_obj, key=None, *, show=True):
    """Attach OpenAIP chart as native, switchable Leaflet overlay."""
    key = key or configured_key()
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
        opacity=0.88,
    ).add_to(map_obj)
    return True
