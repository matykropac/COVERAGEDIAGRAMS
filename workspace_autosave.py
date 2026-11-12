"""Durable, credential-free workspace draft checkpoints.

A draft stores ONLY simple radar configuration and selected flight levels,
never DEM matrices, KML files, OpenTopography/OpenAIP keys, or project results.
Each browser workspace has an unguessable URL token (query parameter "draft").
On local desktop, files live under the user's home directory; on deployed
Streamlit the server must have a persistent writable volume. Session-state
by itself does NOT survive a browser close or server restart.

Only validated, allowlisted keys may be restored. Files are atomically
replaced, permissions restricted where supported, and unchanged content
is not rewritten for every Streamlit rerun.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile

FORMAT="COVERAGEDIAGRAMS_RADAR_DRAFT"
VERSION=1
PARAM_NAME="draft"
TOKEN_RE=re.compile(r"^[a-zA-Z0-9_-]{24,64}$")
MAX_BYTES=65536

RADAR_FIELDS=(
    "ws_radar","ws_lat","ws_lon","ws_radar_site","ws_agl","ws_psr_nm",
    "ws_bearing","ws_beam","ws_ssr_diagram",
    "ws_site_lat_input","ws_site_lon_input","ws_radar_preview_enabled","ws_par_3d_view",
    "ws_min","ws_max","ws_tilt","ws_step","ws_azstep",
    "ws_k","ws_target","ws_reference","ws_source","ws_dataset",
    "ws_par_channels","ws_par_az_beam_step","ws_par_el_beam_step",
    "ws_par_scan_mode","ws_par_scan_loss","ws_par_sector_edge_loss","ws_par_quality",
    "ws_par_gas_loss","ws_par_rain_loss","ws_par_extra_loss",
    "ws_par_detection","ws_par_snr","ws_par_pd","ws_par_pfa",
    "ws_par_pulses","ws_par_level_reference",
    "ws_levels","_par_saved_levels","_par_levels_active",
    "_par_levels_initialized",
)
# Only options/geometry that are safe to preserve as simple values; don't
# inadvertently serialize large geodata, credentials or uploaded files.
OTHER_FIELDS=("ws_section","ws_map_level","ws_display_mode","ws_radar_ui_mode",
              "_radar_active_step","_radar_mode_profiles")

def _root():
    configured=os.environ.get("COVERAGEDIAGRAMS_DRAFT_DIR","").strip()
    return Path(configured).expanduser() if configured else (
        Path.home()/".coveragediagrams"/"drafts")


def new_token():
    return secrets.token_urlsafe(24)


def is_valid_token(token):
    return isinstance(token,str) and TOKEN_RE.fullmatch(token) is not None


def path_for(token):
    if not is_valid_token(token):
        raise ValueError("Neplatný identifikátor pracovního konceptu.")
    return _root()/(token+".json")


def _clean(key,value):
    """Ignore unserializable values and constrain payload shape/size."""
    if key=="ws_radar_site":
        if not isinstance(value,(list,tuple)) or len(value)!=2:
            return None
        if any(type(v) not in (float,int) or not math.isfinite(v) for v in value):
            return None
        lat,lon=map(float,value)
        return [lat,lon] if -80<=lat<=80 and -180<=lon<=180 else None
    if key=="_radar_mode_profiles":
        if not isinstance(value,dict) or set(value)-{"PSR","SSR","ASR","PAR"}:
            return None
        cleaned={}
        for mode,fields in value.items():
            if not isinstance(fields,dict) or len(fields)>len(RADAR_FIELDS):
                return None
            profile={}
            for field,item in fields.items():
                if field not in RADAR_FIELDS:
                    return None
                valid=_clean(field,item)
                if valid is not None:
                    profile[field]=valid
            cleaned[mode]=profile
        return cleaned
    if key in ("ws_levels","_par_saved_levels"):
        if not isinstance(value,(list,tuple)) or len(value)>500:
            return None
        if any(type(x) is not int or not 1<=x<=66000 for x in value):
            return None
        return list(value)
    if key in ("_par_levels_active","_par_levels_initialized","ws_radar_preview_enabled"):
        return value if type(value) is bool else None
    if key in ("ws_site_lat_input","ws_site_lon_input"):
        return value if isinstance(value,str) and len(value)<=32 else None
    if key=="_radar_active_step":
        return value if value in ("STANOVIŠTĚ","ANTÉNA","TERÉN / MODEL","CÍL / FL") else None
    if key in ("ws_radar","ws_reference","ws_source","ws_beam",
               "ws_ssr_diagram","ws_par_channels","ws_par_quality",
               "ws_par_detection","ws_par_scan_mode",
               "ws_par_level_reference","ws_display_mode","ws_section",
               "ws_dataset","ws_radar_ui_mode","ws_par_3d_view"):
        return value if isinstance(value,str) and len(value)<=90 else None
    if key in ("ws_par_pulses","ws_psr_nm","ws_map_level"):
        return value if type(value) is int and abs(value)<100000 else None
    if type(value) in (int,float) and math.isfinite(value) and abs(value)<1000000:
        return value
    return None


def capture(state):
    data={}
    for key in RADAR_FIELDS+OTHER_FIELDS:
        if key in state:
            cleaned=_clean(key,state[key])
            if cleaned is not None:
                data[key]=cleaned
    return data


def export_draft(state):
    """Portable credential-free JSON for users on ephemeral/cloud hosting."""
    payload={"format":FORMAT,"version":VERSION,
             "saved_at":datetime.now(timezone.utc).isoformat(),
             "fields":capture(state)}
    data=json.dumps(payload,ensure_ascii=False,indent=2,
                    allow_nan=False).encode("utf-8")
    if len(data)>MAX_BYTES:
        raise ValueError("Záloha radarových parametrů přesahuje limit.")
    return data


def import_draft(data):
    """Validate portable drafts exactly like on-disk drafts."""
    if not isinstance(data,(bytes,bytearray)) or len(data)>MAX_BYTES:
        raise ValueError("Nesprávný typ nebo velikost zálohy.")
    try:
        raw=json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError,ValueError) as exc:
        raise ValueError("Záloha není platný UTF-8 JSON.") from None
    if not isinstance(raw,dict) or raw.get("format")!=FORMAT or raw.get("version")!=VERSION:
        raise ValueError("Záloha není kompatibilní radarový draft.")
    fields=raw.get("fields")
    if not isinstance(fields,dict) or set(fields)-set(RADAR_FIELDS+OTHER_FIELDS):
        raise ValueError("Záloha obsahuje nepodporované parametry.")
    clean=capture(fields)
    if clean!=fields:
        raise ValueError("Záloha obsahuje neplatné hodnoty.")
    return clean


def read_draft(token):
    path=path_for(token)
    if not path.is_file():
        return None
    if path.stat().st_size>MAX_BYTES:
        raise ValueError("Uložený pracovní koncept je příliš velký.")
    raw=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw,dict) or raw.get("format")!=FORMAT or raw.get("version")!=VERSION:
        raise ValueError("Pracovní koncept má neplatný formát nebo verzi.")
    data=raw.get("fields")
    if not isinstance(data,dict) or set(data)-set(RADAR_FIELDS+OTHER_FIELDS):
        raise ValueError("Pracovní koncept obsahuje nepodporované parametry.")
    cleaned=capture(data)
    if cleaned!=data:
        raise ValueError("Pracovní koncept obsahuje neplatné hodnoty.")
    return {"fields":cleaned,"saved_at":str(raw.get("saved_at",""))}


def save_draft(token,state):
    path=path_for(token)
    previous=read_draft(token)
    # Streamlit discards widget values temporarily hidden by conditional
    # rendering. Keep their LAST VALID values until the user changes them,
    # rather than treating a widget disappearing as an intentional reset.
    fields={**(previous["fields"] if previous else {}),**capture(state)}
    serialized=json.dumps(fields,ensure_ascii=False,sort_keys=True,
                          separators=(",",":"),allow_nan=False).encode("utf-8")
    digest=hashlib.sha256(serialized).hexdigest()
    # No disk write on identical reruns. One atomic write per actual edit.
    if previous is not None:
        prior=json.dumps(previous["fields"],ensure_ascii=False,sort_keys=True,
                         separators=(",",":"),allow_nan=False).encode("utf-8")
        if hashlib.sha256(prior).hexdigest()==digest:
            return False
    path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps({"format":FORMAT,"version":VERSION,
                         "saved_at":datetime.now(timezone.utc).isoformat(),
                         "fields":fields},ensure_ascii=False,
                        separators=(",",":"),allow_nan=False).encode("utf-8")
    if len(payload)>MAX_BYTES:
        raise ValueError("Pracovní koncept přesahuje limit velikosti.")
    fd,tmp=tempfile.mkstemp(prefix=".draft-",suffix=".tmp",dir=path.parent)
    try:
        try:
            os.fchmod(fd,0o600)
        except (AttributeError,OSError):
            pass
        with os.fdopen(fd,"wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return True
