"""Fullscreen EDITOR layout: same map-first floating-workspace concept as VIEWER.

Only presentation CSS. The Streamlit controls, project state, backend calculations,
and persistent Leaflet component remain the same.
"""
FLOATING_EDITOR_CSS = """
<style>
/* Main viewport: map is primary and does not get squeezed by the editor. */
html,body,[data-testid="stApp"],[data-testid="stAppViewContainer"]{
  height:100%;min-height:100%;overflow:hidden!important}
[data-testid="stAppViewContainer"]{background:#081321!important}
[data-testid="stMain"],[data-testid="stMain"]>div{
  width:100%!important;min-width:0!important;max-width:none!important}
[data-testid="stMainBlockContainer"],.block-container{
  max-width:none!important;width:100%!important;min-width:0!important;
  padding:0!important;margin:0!important}
[data-testid="stMainBlockContainer"]>[data-testid="stVerticalBlock"],
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"]{
  gap:0!important}
[data-testid="stMainBlockContainer"] .element-container{
  margin:0!important}
[data-testid="stHeader"]{background:transparent!important;z-index:100004!important;
  pointer-events:none}
[data-testid="stHeader"] button{pointer-events:auto}
/* Sidebar becomes an overlay, instead of taking horizontal space away from Leaflet.
   Preserve Streamlit's own collapsed state and its accessible expand/collapse toggle. */
section[data-testid="stSidebar"]{
  position:fixed!important;left:16px!important;top:62px!important;
  bottom:16px!important;height:calc(100dvh - 78px)!important;
  width:min(560px,calc(100vw - 32px))!important;
  min-width:0!important;max-width:min(560px,calc(100vw - 32px))!important;
  border:1px solid #42617a!important;border-radius:13px!important;
  box-shadow:0 18px 55px #000a!important;
  background:#0b2035f6!important;
  z-index:100003!important;
  overflow:hidden!important;
}
section[data-testid="stSidebar"]>div:first-child,
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{
  width:100%!important;max-width:100%!important;
  background:#0b2035!important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{
  height:100%!important;overflow-y:auto!important;
  overscroll-behavior:contain!important;
  padding:12px 12px 22px!important;
  scrollbar-width:thin!important;
}
/* Keep the tool rail compact but allow the contextual controls to use the width. */
section[data-testid="stSidebar"] .st-key-cd_nav_rail [data-testid="stButton"]>button{
  min-height:43px!important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"]{
  border-radius:8px!important;
}
/* Streamlit alert and status live on top of the map rather than shifting it. */
.st-key-cd_editor_status{
  position:fixed!important;top:14px;left:min(590px,calc(100vw - 330px));
  max-width:min(550px,calc(100vw - 36px));z-index:100002!important;
  padding:3px 9px!important;border:1px solid #345875!important;
  border-radius:10px!important;background:#0b2035e9!important;
  box-shadow:0 10px 28px #0006!important;
  pointer-events:none!important;
}
.st-key-cd_editor_status [data-testid="stAlert"]{
  padding:4px!important;pointer-events:none!important;
}
.st-key-cd_editor_status [data-testid="stCaptionContainer"] p{
  color:#bfe2f9!important;font:11px/1.35 system-ui!important;
}
/* The only editor-map instance stays mounted in a full viewport. */
#cd-persistent-map{height:100dvh!important;width:100%!important;
  min-height:0!important;border:0!important;border-radius:0!important}
.cd-profile-active #cd-persistent-map{height:100dvh!important}
/* Avoid default page spacing / scrolling that causes Leaflet jitter. */
[data-testid="stBottom"],[data-testid="stBottomBlockContainer"]{
  display:none!important}
@media(max-width:700px){
 section[data-testid="stSidebar"]{top:56px!important;left:8px!important;
   bottom:8px!important;height:calc(100dvh - 64px)!important;
   width:calc(100vw - 16px)!important;max-width:calc(100vw - 16px)!important}
 .st-key-cd_editor_status{top:10px;left:58px;right:12px;max-width:none}
}
</style>
"""
