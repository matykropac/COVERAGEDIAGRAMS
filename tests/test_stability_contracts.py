"""Regression guards for VIEWER editing and fixed AMSL engineering inputs.

The browser interaction itself still needs an end-to-end browser runner;
these checks guard the source-level contracts while Python CI is running.
"""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_viewer_has_dedicated_layer_properties_drawer():
    src=(ROOT/"viewer_fullscreen.py").read_text(encoding="utf-8")
    assert "function openLayerProperties(name)" in src
    assert "function closeLayerProperties()" in src
    assert 'className="layer-properties"' in src
    assert 'ed.className="layer-editor"' not in src
    assert 'host.append(drawer)' in src
    assert 'o.geo.setStyle(styleOf(o))' in src
    assert 'data.styles[o.name]=o.style' in src
    for key in ("color","opacity","strokeOpacity","width","radius","dash"):
        assert re.search(r'control\([^\n]*"'+key+r'"',src),key


def test_site_cannot_be_inferred_from_old_default_coordinates():
    src=(ROOT/"map_workspace.py").read_text(encoding="utf-8")
    assert 'def _current_radar_site():' in src
    assert 'st.session_state["ws_radar_site"]=[lat,lon]' in src
    assert 'if _current_radar_site() is None:' in src
    assert '"radar":({"lat":site[0],"lon":site[1]' in src
    assert 'st.session_state["_radar_active_step"]="ANTÉNA"' in src
    assert 'st.session_state["ws_reopen_radar_dialog"]=True' in src


def test_amsl_is_the_only_editable_target_reference():
    src=(ROOT/"map_workspace.py").read_text(encoding="utf-8")
    viewer=(ROOT/"coverage_viewer.py").read_text(encoding="utf-8")
    fullscreen=(ROOT/"viewer_fullscreen.py").read_text(encoding="utf-8")
    assert 'reference="AMSL"' in src
    assert 'st.session_state["ws_reference"]="AMSL"' in src
    assert 'st.session_state["ws_par_level_reference"]="AMSL"' in src
    assert 'st.selectbox("Výška cíle [ft AMSL]",core.STANDARD_LEVELS_FT' in src
    assert 'st.radio("Výška PAR nad terénem / mořem"' not in src
    assert 'st.selectbox("Reference cíle"' not in src
    assert 'reference="AMSL"' in viewer
    assert '"reference": "AMSL"' in fullscreen
    assert 'min="-1000" max="66000"' not in fullscreen
