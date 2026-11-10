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
    """Prefer dedicated tiles token; accept existing OpenAIP data token.

    A number of deployments configured OPENAIP_DATA_API_KEY for aviation
    overlays, but the Leaflet layer previously looked for OPENAIP_API_KEY only.
    Provider API access scope still governs whether tiles are authorized.
    """
    for field in ("OPENAIP_API_KEY","OPENAIP_DATA_API_KEY"):
        value=os.environ.get(field,"").strip()
        if value:
            return value
    try:
        import streamlit as st
        for field in ("OPENAIP_API_KEY","OPENAIP_DATA_API_KEY"):
            value=str(st.secrets.get(field,"")).strip()
            if value:
                return value
    except (FileNotFoundError,KeyError,OSError):
        return None
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

def test_tiles_connection(key=None, *, timeout=7):
    """Probe one fixed OpenAIP tile without returning the API key or URL."""
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    key=key or configured_key()
    if not key:
        return False, "Chybí OPENAIP_API_KEY nebo OPENAIP_DATA_API_KEY v nastavení aplikace."
    url=URL.format(z=6,x=34,y=21,key=quote(key,safe=""))
    try:
        req=Request(url,headers={"User-Agent":"COVERAGEDIAGRAMS-AIP-Check/1.0"})
        with urlopen(req,timeout=timeout) as response:
            code=response.status
            mime=response.headers.get("Content-Type","").lower()
            blob=response.read(24)
        if code==200 and (mime.startswith("image/") or blob[:4]==bytes((137,80,78,71))):
            return True, "OpenAIP HTTP 200: mapová dlaždice je dostupná."
        return False, f"OpenAIP HTTP {code}: odpověď není obrázek."
    except HTTPError as exc:
        reasons={401:"Neplatný či expirovaný API klíč.",
                 403:"Přístup zakázán (oprávnění/omezení klíče).",
                 404:"Mapový endpoint nenalezen.",
                 429:"Limit požadavků překročen.",
                 500:"Chyba na straně OpenAIP.",
                 502:"Chyba brány OpenAIP.",
                 503:"OpenAIP dočasně nedostupný."}
        return False,f"OpenAIP HTTP {exc.code}: {reasons.get(exc.code,'Požadavek odmítnut.')}"
    except (URLError,TimeoutError,OSError):
        return False,"Ze serveru nelze OpenAIP kontaktovat (síť, DNS nebo timeout)."
