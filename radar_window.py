"""Short-lived, unguessable links for opening the live radar in a separate tab."""
import secrets
import time
from urllib.parse import quote

import streamlit as st

TTL_SECONDS = 2 * 60 * 60

@st.cache_resource
def _registry():
    # Shared between Streamlit browser sessions in the same server process.
    return {}

def radar_window_link(result, level_ft, provider):
    registry = _registry()
    now = time.time()
    for key, value in list(registry.items()):
        if now - value["created"] > TTL_SECONDS:
            registry.pop(key, None)
    token = secrets.token_urlsafe(24)
    registry[token] = {"created": now, "result": result,
                       "level": int(level_ft), "provider": provider}
    return "?radar_display=" + quote(token, safe="")

def render_radar_window():
    token = st.query_params.get("radar_display")
    if not token:
        return False
    entry = _registry().get(str(token))
    if entry is None or time.time() - entry["created"] > TTL_SECONDS:
        st.error("Odkaz na radarový displej vypršel. Otevři nový z LIVE SIMULACE.")
        return True
    st.markdown("""<style>
       header[data-testid="stHeader"] {display:none}
       .block-container {max-width:100%;padding:0.5rem 0.7rem 0.2rem}
       [data-testid="stAppViewContainer"] {background:#07121e}
       #MainMenu, footer {visibility:hidden}
    </style>""",unsafe_allow_html=True)
    st.markdown('<div style="color:#e5f5ff;font:600 15px system-ui;padding:5px 8px">📡 RADAR LIVE · samostatný displej</div>',
                unsafe_allow_html=True)
    from live_simulation import _persistent_display
    _persistent_display(entry["result"], entry["level"], entry["provider"])
    return True
