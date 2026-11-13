"""Animated radar feedback during blocking Streamlit operations.

Use with busy_overlay("Title", "Real work phase") as update:
    update("Actual completed phase")
No invented completion percentage, no forced delays, never silently swallows errors.
"""
from contextlib import contextmanager
from html import escape
import streamlit as st

_CSS = """
<style>
@keyframes cd-busy-sweep {from{transform:rotate(0)}to{transform:rotate(360deg)}}
@keyframes cd-busy-pulse {0%,100%{opacity:.18;transform:scale(.8)}50%{opacity:1;transform:scale(1.25)}}
.cd-busy-backdrop{
  position:fixed;inset:0;z-index:2147483000;
  background:rgba(5,16,29,.55);backdrop-filter:blur(4px);
  display:flex;align-items:center;justify-content:center;pointer-events:all;
}
.cd-busy-card{
  position:relative;width:min(390px,calc(100vw - 32px));
  padding:26px 26px 23px;background:#10283d;
  border:1px solid #426b84;border-radius:16px;box-shadow:0 18px 65px #00101f8a;
  color:#e5f5ff;text-align:center;font-family:system-ui,-apple-system,sans-serif;
}
.cd-busy-radar{
  position:relative;margin:0 auto 17px;width:142px;height:142px;border-radius:50%;
  overflow:hidden;border:2px solid #55a6cc;
  background:repeating-radial-gradient(circle,transparent 0px,transparent 22px,#4b93ae72 23px,#4b93ae72 24px),#0a2234;
}
.cd-busy-radar:before{
  content:"";position:absolute;inset:0;
  background:conic-gradient(from 0deg,transparent 0deg,transparent 283deg,#48bce91a 310deg,#69e9ffb3 355deg,transparent 360deg);
  animation:cd-busy-sweep 2s linear infinite;
}
.cd-busy-radar:after{
  content:"";position:absolute;inset:calc(50% - 4px);border-radius:50%;
  background:#85ebff;box-shadow:0 0 14px #6adfff;
}
.cd-busy-cross-x,.cd-busy-cross-y{
  position:absolute;background:#74c2d04a;z-index:1;
}
.cd-busy-cross-x{width:100%;height:1px;top:50%;left:0}
.cd-busy-cross-y{height:100%;width:1px;left:50%;top:0}
.cd-busy-target{
  position:absolute;left:70%;top:27%;width:7px;height:7px;z-index:2;
  border-radius:50%;background:#b4ff9c;box-shadow:0 0 12px #b4ff9c;
  animation:cd-busy-pulse 1.5s ease-in-out infinite;
}
.cd-busy-title{font-size:17px;font-weight:750;letter-spacing:.02em}
.cd-busy-detail{margin-top:8px;font-size:12px;line-height:1.55;color:#b6d1e3;overflow-wrap:anywhere}
.cd-busy-foot{margin-top:17px;color:#79bedc;font-size:10px;letter-spacing:.15em;font-weight:700}
@media(prefers-reduced-motion:reduce){
 .cd-busy-radar:before,.cd-busy-target{animation:none!important}
}
</style>
"""

def _html(title, detail):
    return (_CSS + '<div class="cd-busy-backdrop" role="status" aria-live="polite" aria-label="Zpracovávání dat">'
            '<div class="cd-busy-card"><div class="cd-busy-radar" aria-hidden="true">'
            '<div class="cd-busy-cross-x"></div><div class="cd-busy-cross-y"></div>'
            '<div class="cd-busy-target"></div></div>'
            '<div class="cd-busy-title">'+escape(str(title))+'</div>'
            '<div class="cd-busy-detail">'+escape(str(detail))+'</div>'
            '<div class="cd-busy-foot">COVERAGEDIAGRAMS · RADAR PROCESSING</div>'
            '</div></div>')

@contextmanager
def busy_overlay(title, detail="Pracuji s daty…"):
    holder=st.empty()
    def update(message):
        holder.markdown(_html(title,message),unsafe_allow_html=True)
    update(detail)
    try:
        yield update
    finally:
        holder.empty()
