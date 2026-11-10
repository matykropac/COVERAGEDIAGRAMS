"""Shared COVERAGEDIAGRAMS workstation visual system.

One ATM-inspired palette and consistent spacing across EDITOR and VIEWER.
Pure presentation module; does not modify the radar calculation engine.
"""
import html

NAVY = "#10243b"
CYAN = "#63c9ef"
INK = "#0b1626"
SLATE = "#98b3ca"

COMMON_CSS = """
<style>
:root{--cd-navy:#10243b;--cd-ink:#0b1626;--cd-panel:#14283f;
 --cd-border:#304b65;--cd-cyan:#63c9ef;--cd-text:#e8f3ff;--cd-muted:#9bb4cb}
[data-testid="stAppViewContainer"]{background:#0b1626!important;color:#e7f1ff!important}
[data-testid="stHeader"]{background:#0b1626!important}
[data-testid="stMainBlockContainer"],.block-container{max-width:100%!important;
 padding:9px 16px 16px!important}
[data-testid="stAppViewContainer"] h1,[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3{color:#e7f1ff!important}
[data-testid="stAppViewContainer"] p,[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] [data-testid="stCaptionContainer"]{
 color:#adbed1}
[data-testid="stAppViewContainer"] [data-testid="stVerticalBlock"]{gap:.42rem}
[data-testid="stButton"]>button{
 border-radius:7px!important;border:1px solid #375775!important;
 background:#1b344e!important;color:#e9f5ff!important;
 font-weight:600!important;min-height:33px!important}
[data-testid="stButton"]>button:hover{border-color:#6ac8ec!important;
 color:#fff!important;background:#234a6a!important}
[data-testid="stButton"]>button[kind="primary"]{background:#276c9e!important;
 border-color:#4db2e0!important;color:white!important}
[data-testid="stAppViewContainer"] div[data-baseweb="select"]>div,
[data-testid="stAppViewContainer"] div[data-baseweb="input"]{
 background:#172c43!important;color:#e6f4ff!important;
 border:1px solid #35516d!important;border-radius:6px!important}
[data-testid="stAppViewContainer"] input{color:#e9f3ff!important}
[data-testid="stAppViewContainer"] [data-testid="stExpander"]{
 border:1px solid #354d67!important;background:#12253a!important}
[data-testid="stAppViewContainer"] [data-testid="stFileUploaderDropzone"]{
 background:#142840!important;border-color:#42637f!important}
[data-testid="stAppViewContainer"] [data-testid="stDataFrame"]{
 border:1px solid #34536c!important;border-radius:8px!important}
.cd-app-header{display:flex;align-items:center;justify-content:space-between;
 background:linear-gradient(110deg,#142c46,#10243b 66%,#173b56);
 border:1px solid #35506c;border-radius:10px;padding:10px 17px;
 margin:0 0 9px;min-height:57px;gap:12px;box-shadow:0 8px 26px #05101e3d}
.cd-lockup{display:flex;align-items:center;gap:12px;min-width:0}
.cd-logo{width:36px;height:36px;flex:none}
.cd-brand-title{font:800 18px/1.2 system-ui;color:#f1f8ff;letter-spacing:.055em}
.cd-overline{font:650 9px system-ui;letter-spacing:.22em;color:#7ccbe9;margin-bottom:3px}
.cd-header-meta{font:600 10px system-ui;letter-spacing:.1em;color:#a4c5da;text-align:right}
.cd-header-meta strong{display:block;color:#e1f2fc;font-size:12px;letter-spacing:.04em}
.cd-rail-label{font:650 9px system-ui;text-align:center;color:#8fbad3;
 letter-spacing:.045em;margin-top:-4px}
.cd-panel-title{font:750 12px system-ui;color:#d8edfc;letter-spacing:.11em;
 border-bottom:1px solid #345572;padding-bottom:8px;margin:4px 0 12px}
.cd-statusbar{border:1px solid #30485e;background:#11243a;border-radius:6px;
 color:#9ebad0;padding:7px 11px;font:600 10px system-ui;letter-spacing:.06em}
@media(max-width:800px){.cd-header-meta{display:none}.cd-brand-title{font-size:15px}}
</style>
"""

LOGO = """<svg class="cd-logo" viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<circle cx="20" cy="20" r="18" fill="#183f5c" stroke="#5fc9f3" stroke-width="1.4"/>
<circle cx="20" cy="20" r="12" fill="none" stroke="#5fc9f3" stroke-opacity=".42"/>
<circle cx="20" cy="20" r="6" fill="none" stroke="#5fc9f3" stroke-opacity=".46"/>
<path d="M20 20L34 9" stroke="#9ae9fc" stroke-width="2.3" stroke-linecap="round"/>
<path d="M20 20L30 5" fill="#5fc9f3" opacity=".2"/>
<circle cx="20" cy="20" r="2.4" fill="#8be7fb"/>
<circle cx="27" cy="13" r="2" fill="#f8d77b"/>
</svg>"""


def header(mode, project="", status="ENGINEERING CONSOLE"):
    """Escaped display metadata, never interpreted as user HTML."""
    return (
        '<div class="cd-app-header"><div class="cd-lockup">'+LOGO+
        '<div><div class="cd-overline">GEOSPATIAL ENGINEERING PLATFORM / '+
        html.escape(mode.upper())+
        '</div><div class="cd-brand-title">COVERAGEDIAGRAMS</div></div></div>'+
        '<div class="cd-header-meta"><strong>'+html.escape(project or "UNTITLED PROJECT")+
        '</strong>'+html.escape(status)+'</div></div>'
    )
