"""Fullscreen standalone VIEWER: browser-side layer manager and persistent Leaflet."""
from __future__ import annotations

import base64
import gzip
import json

import numpy as np
import radar_core as core
import streamlit as st
import streamlit.components.v1 as components


def render_fullscreen_viewer(layers, styles, center, *, diagnostic_result=None,
                             diagnostic_levels=(), snapshot="", three_d_url="", studio_url=""):
    """Only mount one map. UI edits, import and filtering never rerun Streamlit."""
    # Base64 avoids closing the embedded script or injecting HTML from imported data.
    # Native grid: no second DEM sampler, no speculative covered points.
    # Compression avoids sending megabytes of repetitive JSON through the iframe.
    diagnostics = None
    if diagnostic_result is not None:
        result = diagnostic_result
        cfg = result["config"]
        levels = [int(ft) for ft in diagnostic_levels
                  if core.valid_flight_level(cfg.radar_mode, ft)]
        if not levels:
            levels = [int(ft) for ft in core.flight_levels_for(cfg.radar_mode)[:3]]
        levels = list(dict.fromkeys(levels))[:80]
        grid = {
            "az": np.round(result["az"], 6).tolist(),
            "distance": np.round(result["distance"], 3).tolist(),
            "terrain": np.where(np.isfinite(result["terrain"]), result["terrain"], np.nan).tolist(),
            "lower": result["lower"].tolist(),
            "upper": result["upper"].tolist(),
            "antenna": float(result["antenna"]),
            "k": float(cfg.k),
            "minElev": float(cfg.min_elev),
            "maxElev": float(cfg.max_elev),
            "bearing": float(cfg.bearing_deg),
            "radarMode": str(cfg.radar_mode),
            "levels": levels,
            "status": {},
        }
        for ft in levels:
            values = core.status_at_height(result, ft * core.FT_TO_M)
            # 2: unknown, 0: blocked, 1: covered.
            grid["status"][str(ft)] = np.where(
                np.isfinite(values), np.asarray(np.nan_to_num(values), dtype=np.uint8), 2
            ).tolist()
        raw = json.dumps(grid, ensure_ascii=False, allow_nan=True,
                         separators=(",", ":")).encode("utf-8")
        diagnostics = base64.b64encode(gzip.compress(raw, compresslevel=5)).decode("ascii")
    encoded=base64.b64encode(json.dumps({
        "layers":layers,
        "styles":styles,
        "center":[float(center[0]),float(center[1])],
        "snapshot":str(snapshot),
        "threeDUrl":str(three_d_url),
        "studioUrl":str(studio_url),
        "diagnostics":diagnostics,
    },ensure_ascii=False,allow_nan=False).encode("utf-8")).decode("ascii")
    page=_HTML.replace("__VIEWER_PAYLOAD__",encoded)
    st.markdown("""<style>
    header[data-testid="stHeader"],[data-testid="stToolbar"],
    [data-testid="stDecoration"],footer,[data-testid="stSidebar"]{display:none!important}
    [data-testid="stAppViewContainer"]{background:#081321!important}
    [data-testid="stMainBlockContainer"],.block-container{
        max-width:none!important;padding:0!important;margin:0!important}
    [data-testid="stMainBlockContainer"] > div,[data-testid="stVerticalBlock"]{
        gap:0!important}
    [data-testid="stIFrame"]{
        width:100vw!important;height:100dvh!important;display:block!important;
        border:0!important}
    iframe[title="cd-fullscreen-viewer"]{height:100dvh!important}
    </style>""",unsafe_allow_html=True)
    # iframe height is also overridden by the viewport rule above.
    components.html(page,height=950,scrolling=False)


_HTML=r"""<!doctype html><html lang="cs"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js"></script>
<style>
*{box-sizing:border-box}html,body,#map{margin:0;width:100%;height:100%;overflow:hidden}
body{font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;background:#071320;color:#eaf2ff}
#map{background:#0e2235}
.leaflet-container{background:#0e2235;font:inherit}
.leaflet-control-zoom{margin-top:74px!important;margin-right:16px!important}
.leaflet-control-zoom a{background:#112842!important;color:#eaf2ff!important;border-color:#35536a!important}
.leaflet-control-attribution{background:#09182bcc!important;color:#b3c8da!important}
.toolbar{position:absolute;z-index:1000;top:14px;left:16px;display:flex;gap:7px;align-items:center;max-width:calc(100vw - 100px)}
.brand{display:flex;align-items:center;gap:9px;padding:10px 14px;background:#0b2035f2;border:1px solid #365676;border-radius:12px;
font-weight:800;letter-spacing:.095em;white-space:nowrap;box-shadow:0 8px 30px #0005}
.brand small{font-weight:500;letter-spacing:0;color:#7fc8e7}
button,.fakebtn{cursor:pointer;font:inherit;color:#ecf7ff;background:#153451;border:1px solid #3b6281;border-radius:9px;padding:9px 12px;white-space:nowrap}
button:hover,.fakebtn:hover{background:#235071;border-color:#6fbbdf}
button.primary{background:#087aaf;border-color:#40b7e7;font-weight:750}
button.ghost{background:#0b2035ef}
button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #63d0ff;outline-offset:2px}
.panel{position:absolute;z-index:1100;top:70px;left:16px;width:365px;max-width:calc(100vw - 32px);
height:min(750px,calc(100dvh - 94px));display:flex;flex-direction:column;
background:#0b2035f7;border:1px solid #456582;border-radius:15px;box-shadow:0 16px 55px #0008;
backdrop-filter:blur(12px)}
.panel.hidden{display:none}
.panel header{display:flex;gap:7px;padding:12px;border-bottom:1px solid #2a4a66;align-items:center}
.panel header strong{flex:1;font-size:13px;letter-spacing:.08em}
.panel header button{padding:5px 10px}
.tabs{display:flex;gap:5px;padding:9px 12px 0}
.tabs button{flex:1;padding:8px 3px;font-size:12px}
.tabs button.active{background:#195f87;border-color:#5bc3e8}
.section{flex:1;overflow:auto;min-height:0;padding:13px}
.section[hidden]{display:none}
h3{font-size:11px;letter-spacing:.12em;color:#83d8fd;margin:4px 0 13px}
.muted{color:#9bb4c9;font-size:11px;line-height:1.5}
.field{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:10px 0}
.field label{font-size:12px;color:#d7e5f0}
.field input[type=range]{width:140px}
input[type=text],input[type=search],select,input[type=number]{background:#102a42;color:#f1f7ff;border:1px solid #3c5d78;border-radius:7px;padding:9px;min-width:0}
select{max-width:190px}.wide{width:100%;max-width:none!important}
.actions{display:flex;gap:6px;margin:9px 0}.actions button{flex:1}
input[type=checkbox]{accent-color:#0aa5e8;cursor:pointer}
#layer-list{display:flex;flex-direction:column;gap:7px;overflow:auto;padding-bottom:10px}
.layer{display:grid;grid-template-columns:19px 1fr 31px;align-items:center;gap:8px;padding:9px;
background:#122d46;border:1px solid #2c4b64;border-radius:9px}
.layer.off{opacity:.56}.layer .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
.layer small{display:block;font-size:10px;color:#97b5c9}
.layer button{padding:5px 6px;font-size:13px}
.layer-editor{grid-column:1/-1;background:#092038;border:1px solid #2d5473;border-radius:8px;padding:9px}
.layer-editor .field{margin:5px 0}
.layer-editor input[type=color]{height:31px;width:45px;background:none;border:0}
.note{border:1px solid #325772;background:#0b2942;border-radius:9px;padding:9px 10px;margin:10px 0;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}
.note.error{border-color:#b65a61;color:#ffb2b8}
.inspection{position:absolute;right:16px;top:72px;z-index:1150;width:min(540px,calc(100vw - 32px));
 max-height:calc(100dvh - 135px);overflow:auto;padding:12px 15px;background:#0b2035f7;
 border:1px solid #4a7d9a;border-radius:12px;box-shadow:0 15px 40px #0009}
.inspection header{display:flex;align-items:center;justify-content:space-between;color:#85d9ff;font-size:12px;letter-spacing:.05em}
.inspection header button{padding:4px 10px}.inspection svg{display:block;width:100%;background:#07182a;border-radius:7px;margin:10px 0}
.inspection #inspection-details{font-size:12px;white-space:pre-line}
@media(max-width:680px){.inspection{top:63px;right:8px;width:calc(100vw - 16px);max-height:50dvh}}
.status{position:absolute;bottom:22px;right:16px;z-index:1000;
background:#0a2136e8;border:1px solid #315873;padding:7px 11px;border-radius:9px;
font-size:11px;pointer-events:none;max-width:50vw}
#drop{position:absolute;inset:0;z-index:2000;background:#071e34cc;border:4px dashed #5acfff;display:none;place-items:center;font-size:25px;font-weight:800;pointer-events:none}
#drop.on{display:grid}
#file{display:none}
@media(max-width:680px){.brand small{display:none}.brand{padding:9px}.toolbar{gap:5px;left:8px;top:8px}.toolbar button{padding:9px 8px;font-size:11px}
.panel{left:8px;top:60px;width:calc(100vw - 16px);height:calc(100dvh - 77px)}.status{bottom:16px;right:8px}}
</style></head><body>
<div id="map" role="application" aria-label="Interaktivní mapa VIEWER"></div>
<div class="toolbar">
  <div class="brand">◈ VIEWER <small>GEOSPATIAL WORKSPACE</small></div>
  <button id="panel-toggle" class="primary" aria-expanded="true">☷ Nastavení</button>
  <button id="quick-open" class="ghost">＋ Soubor</button>
  <button id="fit" class="ghost">◎ Přiblížit data</button>
  <button id="inspect" class="ghost" aria-pressed="false">⌖ BOD / PROFIL</button>
  <button id="go3d" class="ghost" hidden>◈ 3D okno</button>
  <button id="print-studio" class="ghost">⇩ Export studio</button>
</div>
<div class="panel" id="panel">
 <header><strong>MAP WORKSPACE</strong><span id="count" class="muted">0 vrstev</span><button id="close" aria-label="Zavřít panel">×</button></header>
 <div class="tabs"><button class="active" data-tab="layers">VRSTVY</button><button data-tab="source">IMPORT</button><button data-tab="map">MAPA / EXPORT</button></div>
 <section class="section" id="tab-layers">
   <input id="search" type="search" class="wide" placeholder="Filtrovat názvy vrstev / objektů…">
   <div class="actions"><button id="all">Vše</button><button id="none">Nic</button><button id="invert">Invertovat</button></div>
   <div class="muted" id="layer-stats"></div><div id="layer-list"></div>
 </section>
 <section class="section" id="tab-source" hidden>
   <h3>NAČTENÍ GEODAT</h3>
   <button id="load" class="primary wide">＋ Načíst KML / KMZ / GeoJSON / CDVIEW</button>
   <p class="muted">Lze také přetáhnout soubory přímo do mapy. Importované vrstvy se přidají k existujícím; projekt CDVIEW obnoví celé pracovní prostředí.</p>
   <div class="actions"><button id="clear">Odstranit všechny vrstvy</button></div>
   <div id="notice" class="note">Mapové ovládání běží přímo v prohlížeči. Posouvání, zoom a změny vrstev neaktualizují Streamlit.</div>
 </section>
 <section class="section" id="tab-map" hidden>
   <h3>MAPOVÁ KOMPOZICE</h3>
   <div class="field"><label for="base">Podkladová mapa</label><select id="base">
     <option value="osm">OpenStreetMap</option><option value="imagery">Esri World Imagery</option>
     <option value="topo">Esri Topographic</option><option value="dark">CARTO Dark</option>
     <option value="opentopo">OpenTopoMap</option></select></div>
   <div class="field"><label for="labels">Popisky objektů</label><input id="labels" type="checkbox" checked></div>
   <div class="field"><label for="legend">Legenda</label><input id="legend" type="checkbox" checked></div>
   <div class="field"><label for="range-on">RANGE kružnice</label><input id="range-on" type="checkbox"></div>
   <div class="field"><label for="range">RANGE [NM]</label><input id="range" type="range" min="1" max="260" value="20"><strong id="range-text">20</strong></div>
   <div class="muted" id="range-center">Střed: radar</div>
   <h3 style="margin-top:24px">EXPORT</h3>
   <div class="actions"><button id="save-geo">GeoJSON</button><button id="save-project">Projekt CDVIEW</button></div>
   <p class="muted">GeoJSON obsahuje právě zobrazené objekty. CDVIEW uchovává všechny vrstvy, nastavení, jejich barvy a viditelnost.</p>
 </section>
</div>
<aside id="inspection" class="inspection" hidden>
  <header><strong>⌖ ANALÝZA BODU / LINE OF SIGHT</strong><button id="inspection-close" aria-label="Zavřít analýzu">×</button></header>
  <div class="field"><label for="inspection-level">Výška cíle [ft AMSL]</label><select id="inspection-level"></select></div>
  <div id="inspection-result" class="note">Klikni na libovolný bod v mapě.</div>
  <svg id="inspection-profile" viewBox="0 0 520 184" role="img" aria-label="Terénní profil a spojnice přímé viditelnosti"></svg>
  <div id="inspection-details" class="muted"></div>
</aside>
<div id="status" class="status">Načítám mapu…</div>
<div id="drop">PUSŤ SOUBORY DO MAPY</div><input id="file" type="file" accept=".kml,.kmz,.json,.geojson,.cdview" multiple>
<script>
const DATA=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob("__VIEWER_PAYLOAD__"),c=>c.charCodeAt(0))));
const $=id=>document.getElementById(id);
const BASES={
 osm:["https://tile.openstreetmap.org/{z}/{x}/{y}.png","© OpenStreetMap contributors"],
 imagery:["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}","Tiles © Esri"],
 topo:["https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}","Tiles © Esri"],
 dark:["https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png","© OpenStreetMap © CARTO"],
 opentopo:["https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png","© OpenTopoMap, OpenStreetMap"]
};
const COLORS=["#3fa7fa","#21d7bf","#dc8aff","#ffb058","#fc647e","#a6d67b"];
let layers=new Map(),map=null,base=null,rangeShape=null,openedEditor=null,vectorRenderer=null;
let grid=null, inspectEnabled=false, selectedPoint=null, inspectionLine=null, inspectionMarker=null;
let setting={base:"dark",labels:true,legend:true,range:false,nm:20};
let layerSeq=0,chosenBase="dark",radarCenter=DATA.center||[50,15],legendControl=null;
const escapeHTML=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const filename=s=>String(s||"import").slice(0,180);
const status=t=>{$("status").textContent=t};
function notify(t,error=false){$("notice").textContent=t;$("notice").classList.toggle("error",error);status(t)}
function validFeature(f){return f&&f.type==="Feature"&&f.geometry&&typeof f.geometry.type==="string"}
function initialStyle(s,i){return {show:s?.show!==false,color:/^#[0-9a-f]{6}$/i.test(s?.color||"")?s.color:COLORS[i%COLORS.length],
 opacity:Number.isFinite(Number(s?.opacity))?Math.max(0,Math.min(1,Number(s.opacity))):.35,
 width:Number.isFinite(Number(s?.width))?Math.max(.5,Math.min(12,Number(s.width))):2}}
function addLayer(name,features,style,rerender=true){
 if(!Array.isArray(features))return;
 const good=features.filter(validFeature);
 if(!good.length)return;
 let unique=String(name||"Layer");let index=2;while(layers.has(unique))unique=String(name||"Layer")+" ("+(index++)+")";
 layers.set(unique,{name:unique,features:good,style:initialStyle(style,layerSeq++),geo:null,attached:false});
 if(rerender){refreshList();syncAll();fitAll()}
}
function resetLayers(){for(const o of layers.values())if(o.geo)map.removeLayer(o.geo);layers.clear();openedEditor=null}
function styleOf(o){return {color:o.style.color,weight:o.style.width,opacity:1,fillColor:o.style.color,fillOpacity:o.style.opacity}}
function ensureGeo(o){
 if(o.geo)return;
 o.geo=L.geoJSON({type:"FeatureCollection",features:o.features},{
  renderer:vectorRenderer,
  style:()=>styleOf(o),
  pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:4,...styleOf(o)}),
  onEachFeature:(f,l)=>{const p=f.properties||{};const name=p.name||p.Name||p.title;
    if(name)l.bindTooltip(escapeHTML(name),{sticky:true,permanent:false});
    if(p.description)l.bindPopup("<b>"+escapeHTML(name||o.name)+"</b><p>"+escapeHTML(p.description).slice(0,1200)+"</p>")
  }
 });
}
function syncOne(o){if(o.style.show){ensureGeo(o);if(!map.hasLayer(o.geo))o.geo.addTo(map);o.geo.setStyle(styleOf(o))}
 else if(o.geo&&map.hasLayer(o.geo))map.removeLayer(o.geo)}
function syncAll(){for(const o of layers.values())syncOne(o);refreshLegend();updateCount()}
function updateCount(){let n=0;for(const o of layers.values())if(o.style.show)n++;
 $("count").textContent=n+" / "+layers.size+" vrstev";$("layer-stats").textContent="Zobrazeno "+n+" z "+layers.size+" vrstev"}
function renderLayerRow(o,filter){
 const search=(filter||"").toLocaleLowerCase();
 const nameMatch=o.name.toLocaleLowerCase().includes(search);
 const matched=search?o.features.filter(f=>String(f.properties?.name||f.properties?.Name||"").toLocaleLowerCase().includes(search)):null;
 if(search&&!nameMatch&&!matched.length)return null;
 const row=document.createElement("div");row.className="layer"+(o.style.show?"":" off");
 const check=document.createElement("input");check.type="checkbox";check.checked=o.style.show;check.setAttribute("aria-label","Zobrazit "+o.name);
 check.addEventListener("change",()=>{o.style.show=check.checked;syncOne(o);refreshLegend();updateCount();row.classList.toggle("off",!check.checked)});
 const desc=document.createElement("div");desc.innerHTML='<div class="name" title="'+escapeHTML(o.name)+'">'+escapeHTML(o.name)+'</div><small>'+o.features.length.toLocaleString("cs")+" objektů"+(matched&&!nameMatch?" · shoda "+matched.length:"")+"</small>";
 const edit=document.createElement("button");edit.textContent="⚙";edit.setAttribute("aria-label","Vlastnosti "+o.name);
 edit.addEventListener("click",()=>{openedEditor=openedEditor===o.name?null:o.name;refreshList()});
 row.append(check,desc,edit);
 if(openedEditor===o.name){
  const ed=document.createElement("div");ed.className="layer-editor";
  const fields=[["Barva","color","color",o.style.color],["Průhlednost výplně","opacity","range",Math.round(o.style.opacity*100)],["Tloušťka linie","width","range",o.style.width]];
  for(const [label,key,type,value] of fields){
   const div=document.createElement("div");div.className="field";
   const lbl=document.createElement("label");lbl.textContent=label;
   const input=document.createElement("input");input.type=type;input.value=value;
   if(key==="opacity"){input.min=0;input.max=100;input.step=5}
   if(key==="width"){input.min=.5;input.max=10;input.step=.5}
   input.addEventListener("input",()=>{o.style[key]=key==="color"?input.value:key==="opacity"?Number(input.value)/100:Number(input.value);
      if(o.geo)o.geo.setStyle(styleOf(o));refreshLegend()});
   div.append(lbl,input);ed.append(div);
  }
  const del=document.createElement("button");del.textContent="Odstranit vrstvu";del.addEventListener("click",()=>{
    if(o.geo)map.removeLayer(o.geo);layers.delete(o.name);openedEditor=null;refreshList();refreshLegend()});
  ed.append(del);row.append(ed);
 }
 return row;
}
function refreshList(){
 const list=$("layer-list");list.replaceChildren();const filter=$("search").value.trim();
 for(const o of layers.values()){const row=renderLayerRow(o,filter);if(row)list.appendChild(row)}
 updateCount();
}
function refreshLegend(){
 if(legendControl){map.removeControl(legendControl);legendControl=null}
 if(!setting.legend)return;
 const active=[...layers.values()].filter(o=>o.style.show);
 if(!active.length)return;
 legendControl=L.control({position:"bottomleft"});
 legendControl.onAdd=()=>{const box=L.DomUtil.create("div","viewer-legend");
 box.style.cssText="max-height:210px;overflow:auto;max-width:290px;background:#0b2035ed;border:1px solid #496a84;border-radius:9px;padding:9px 11px;color:#ecf7ff;font:11px system-ui";
 const top=document.createElement("strong");top.textContent="VRSTVY · "+active.length;box.append(top);
 for(const o of active.slice(0,35)){const div=document.createElement("div");div.style.cssText="display:flex;gap:6px;margin-top:5px;align-items:center";
 const swatch=document.createElement("i");swatch.style.cssText="width:13px;height:8px;background:"+o.style.color+";display:inline-block;flex-shrink:0";
 const txt=document.createElement("span");txt.textContent=o.name;div.append(swatch,txt);box.append(div)}
 L.DomEvent.disableClickPropagation(box);return box};legendControl.addTo(map)
}
function fitAll(){
 const group=L.featureGroup([...layers.values()].filter(o=>o.style.show&&o.geo).map(o=>o.geo));
 try{const b=group.getBounds();if(b.isValid())map.fitBounds(b.pad(.08),{animate:false,maxZoom:12});else map.setView(radarCenter,8,{animate:false})}
 catch(e){status("Rozsah dat nelze určit: "+e.message)}
}
function selectBase(k){
 if(!(k in BASES))return;
 if(base)map.removeLayer(base);
 chosenBase=k;setting.base=k;
 const [url,attr]=BASES[k];base=L.tileLayer(url,{attribution:attr,maxZoom:19,updateWhenIdle:true,
   keepBuffer:4,crossOrigin:false}).addTo(map);base.bringToBack();$("base").value=k;
}
function wgs84Destination(latDeg,lonDeg,azDeg,distance){
 // Vincenty direct problem on WGS84, distance in metres, azimuth clockwise from true north.
 const a=6378137,f=1/298.257223563,b=a*(1-f);
 const phi=latDeg*Math.PI/180,alpha1=azDeg*Math.PI/180;
 const U1=Math.atan((1-f)*Math.tan(phi)),sinU1=Math.sin(U1),cosU1=Math.cos(U1);
 const sinA1=Math.sin(alpha1),cosA1=Math.cos(alpha1);
 const sigma1=Math.atan2(Math.tan(U1),cosA1);
 const sinAlpha=cosU1*sinA1,cosSqAlpha=1-sinAlpha*sinAlpha;
 const uSq=cosSqAlpha*(a*a-b*b)/(b*b);
 const A=1+uSq/16384*(4096+uSq*(-768+uSq*(320-175*uSq)));
 const B=uSq/1024*(256+uSq*(-128+uSq*(74-47*uSq)));
 let sigma=distance/(b*A),delta=0;
 for(let i=0;i<40;i++){
   const cos2=Math.cos(2*sigma1+sigma),sinS=Math.sin(sigma),cosS=Math.cos(sigma);
   delta=B*sinS*(cos2+B/4*(cosS*(-1+2*cos2*cos2)-
     B/6*cos2*(-3+4*sinS*sinS)*(-3+4*cos2*cos2)));
   const next=distance/(b*A)+delta;
   if(Math.abs(next-sigma)<1e-12){sigma=next;break}
   sigma=next;
 }
 const sinS=Math.sin(sigma),cosS=Math.cos(sigma);
 const tmp=sinU1*sinS-cosU1*cosS*cosA1;
 const phi2=Math.atan2(sinU1*cosS+cosU1*sinS*cosA1,
   (1-f)*Math.sqrt(sinAlpha*sinAlpha+tmp*tmp));
 const lambda=Math.atan2(sinS*sinA1,cosU1*cosS-sinU1*sinS*cosA1);
 const C=f/16*cosSqAlpha*(4+f*(4-3*cosSqAlpha));
 const L=lambda-(1-C)*f*sinAlpha*(sigma+C*sinS*
   (Math.cos(2*sigma1+sigma)+C*cosS*(-1+2*Math.cos(2*sigma1+sigma)**2)));
 return [phi2*180/Math.PI,((lonDeg+L*180/Math.PI+540)%360)-180];
}
function updateRange(){
 if(rangeShape){map.removeLayer(rangeShape);rangeShape=null}
 const nm=Number($("range").value);setting.nm=nm;$("range-text").textContent=nm;
 if(!$("range-on").checked)return;
 const pts=[];
 for(let a=0;a<=360;a+=2)pts.push(wgs84Destination(radarCenter[0],radarCenter[1],a,nm*1852));
 rangeShape=L.polyline(pts,{color:"#4fd5ff",weight:2,dashArray:"7,5",interactive:false}).addTo(map);
}
function geometry(node){
 const ns="http://www.opengis.net/kml/2.2";
 const find=(n,tag)=>n.getElementsByTagNameNS(ns,tag)[0]||n.getElementsByTagName(tag)[0];
 const all=(n,tag)=>[...n.getElementsByTagName("*")].filter(x=>x.localName===tag);
 const coords=n=>String(find(n,"coordinates")?.textContent||"").trim().split(/\s+/).map(s=>s.split(",").map(Number)).filter(v=>v.length>=2&&v.every(Number.isFinite));
 const multi=[...node.children].find(x=>x.localName==="MultiGeometry");
 if(multi){const geometries=[...multi.children].map(geometry).filter(Boolean);
   return geometries.length?{type:"GeometryCollection",geometries}:null}
 const point=node.localName==="Point"?node:find(node,"Point");if(point){const c=coords(point);return c.length?{type:"Point",coordinates:c[0]}:null}
 const line=node.localName==="LineString"?node:find(node,"LineString");if(line){const c=coords(line);return c.length>1?{type:"LineString",coordinates:c}:null}
 const poly=node.localName==="Polygon"?node:find(node,"Polygon");if(poly){
   const outer=find(poly,"outerBoundaryIs");const rings=[];
   if(outer)rings.push(coords(outer));for(const inner of all(poly,"innerBoundaryIs"))rings.push(coords(inner));
   return rings[0]?.length>=3?{type:"Polygon",coordinates:rings}:null}
 return null;
}
function parseKML(xml,file){
 const doc=new DOMParser().parseFromString(xml,"application/xml");
 if(doc.querySelector("parsererror"))throw Error("Neplatný XML/KML");
 const ns="http://www.opengis.net/kml/2.2";
 const matches=(el,n)=>el.localName===n;
 const first=(el,n)=>[...el.children].find(x=>matches(x,n));
 const name=el=>first(el,"name")?.textContent?.trim();
 const groups=new Map();
 function traverse(node,group){
  for(const child of node.children){
   if(matches(child,"Document"))traverse(child,group);
   else if(matches(child,"Folder"))traverse(child,name(child)||group);
   else if(matches(child,"Placemark")){
    const geo=geometry(child);if(!geo)continue;
    if(!groups.has(group))groups.set(group,[]);
    groups.get(group).push({type:"Feature",properties:{name:name(child)||"Unnamed",source:file,
       description:first(child,"description")?.textContent||""},geometry:geo});
   }
  }
 }
 traverse(doc.documentElement,"Imported");return groups;
}
async function loadFile(file){
 if(file.size>60*1024*1024)throw Error("Soubor přesahuje limit 60 MB");
 const lower=file.name.toLowerCase();
 if(lower.endsWith(".cdview")){
  if(!window.JSZip)throw Error("Modul JSZip není dostupný");
  const zip=await JSZip.loadAsync(file);const member=zip.file("viewer.json");
  if(!member)throw Error("CDVIEW neobsahuje viewer.json");
  const raw=await member.async("string");if(raw.length>150*1024*1024)throw Error("Projekt je příliš velký");
  const obj=JSON.parse(raw);
  if(obj.format!=="COVERAGEDIAGRAMS_VIEWER"||obj.version!==1||!obj.layers||!obj.styles)throw Error("Neplatný CDVIEW projekt");
  resetLayers();let idx=0;
  for(const [name,features] of Object.entries(obj.layers)){
    if(++idx>300)throw Error("Příliš mnoho vrstev");addLayer(name,features,obj.styles[name],false)}
  setting.base=BASES[obj.settings?.viewer_basemap]?obj.settings.viewer_basemap:(
    Object.keys(BASES).includes(obj.settings?.base)?obj.settings.base:"dark");
  selectBase(setting.base);refreshList();syncAll();fitAll();
  return "Projekt načten: "+layers.size+" vrstev";
 }
 let xml=null;
 if(lower.endsWith(".kmz")){
  if(!window.JSZip)throw Error("Modul JSZip není dostupný");
  const zip=await JSZip.loadAsync(file);const names=Object.keys(zip.files).filter(n=>n.toLowerCase().endsWith(".kml"));
  if(!names.length)throw Error("KMZ neobsahuje KML");
  const member=zip.file(names.find(n=>n.toLowerCase().endsWith("/doc.kml"))||names[0]);
  if(member._data?.uncompressedSize>30*1024*1024)throw Error("KML v KMZ je příliš velký");
  xml=await member.async("string");
 }else if(lower.endsWith(".kml"))xml=await file.text();
 if(xml!==null){
  const groups=parseKML(xml,file.name);for(const [name,features] of groups)addLayer(file.name+" / "+name,features,null,false);
 }else if(lower.endsWith(".geojson")||lower.endsWith(".json")){
  const obj=JSON.parse(await file.text());
  const fs=obj.type==="FeatureCollection"?obj.features:obj.type==="Feature"?[obj]:null;
  if(!Array.isArray(fs))throw Error("Nepodporovaný GeoJSON");
  addLayer(file.name,fs,null,false);
 }else throw Error("Nepodporovaný formát");
 refreshList();syncAll();fitAll();return "Načteno: "+file.name;
}
async function importFiles(files){
 let messages=[],errors=[];
 for(const f of [...files]){try{messages.push(await loadFile(f))}catch(e){errors.push(filename(f)+": "+e.message)}}
 notify([...messages,...errors].join("\n")||"Žádná data",errors.length>0);
}
function download(name,blob){
 const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=name;
 document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500)
}
async function saveCDView(){
 if(!window.JSZip){notify("JSZip není dostupný",true);return}
 const data={format:"COVERAGEDIAGRAMS_VIEWER",version:1,layers:{},styles:{},
  settings:{base:setting.base,viewer_basemap:setting.base,viewer_mode:"2D MAPA",
   viewer_legend:setting.legend,viewer_north:true}};
 for(const o of layers.values()){data.layers[o.name]=o.features;data.styles[o.name]=o.style}
 const zip=new JSZip();zip.file("viewer.json",JSON.stringify(data));
 download("COVERAGEDIAGRAMS_viewer.cdview",await zip.generateAsync({type:"blob",compression:"DEFLATE"}));
}
function saveGeo(){
 const fs=[];for(const o of layers.values())if(o.style.show)fs.push(...o.features);
 download("COVERAGEDIAGRAMS_visible.geojson",new Blob([JSON.stringify({type:"FeatureCollection",features:fs})],{type:"application/geo+json"}))
}
async function loadDiagnostics(){
 if(!DATA.diagnostics){$("inspect").title="Nejprve otevři VIEWER z vypočteného projektu EDITORU";return}
 try{
  const bytes=Uint8Array.from(atob(DATA.diagnostics),c=>c.charCodeAt(0));
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  grid=JSON.parse(await new Response(stream).text());
  const select=$("inspection-level");
  for(const ft of grid.levels){const option=document.createElement("option");option.value=ft;option.textContent=ft.toLocaleString("cs")+" ft";select.add(option)}
  select.onchange=showInspection;
  $("inspect").title="Výběr bodu s diagnostikou výpočtu krytí";
 }catch(e){notify("Diagnostická síť se nepodařila otevřít: "+e.message,true)}
}
function radialAt(lat,lon){
 // WGS84 geodesic inverse (spherical initial estimate only to choose the nearest
 // native polar grid cell; the displayed point snaps to the WGS84 native sample).
 const p1=radarCenter[0]*Math.PI/180,p2=lat*Math.PI/180;
 const dl=(lon-radarCenter[1])*Math.PI/180,dp=p2-p1;
 const a=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
 const distance=6371008.8*2*Math.atan2(Math.sqrt(a),Math.sqrt(Math.max(0,1-a)));
 const bearing=(Math.atan2(Math.sin(dl)*Math.cos(p2),Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl))*180/Math.PI+360)%360;
 return {distance,bearing};
}
function showInspection(){
 if(!grid||!selectedPoint)return;
 const {distance,bearing}=radialAt(selectedPoint.lat,selectedPoint.lng);
 const delta=((bearing-grid.bearing+540)%360)-180;
 const inside=grid.radarMode!=="PAR-NG"||Math.abs(delta)<=15+1e-8;
 const select=(arr,x)=>arr.reduce((best,v,i)=>Math.abs(v-x)<Math.abs(arr[best]-x)?i:best,0);
 const i=select(grid.az,grid.radarMode==="PAR-NG"?grid.bearing+delta:bearing);
 const j=select(grid.distance,distance);
 if(!inside||distance>grid.distance.at(-1)||distance<0){
  $("inspection-result").textContent="MIMO VÝPOČETNÍ DOMÉNU · bod leží mimo sektor nebo dosah radaru.";
  $("inspection-profile").replaceChildren();$("inspection-details").textContent="Zvolený azimut: "+bearing.toFixed(2)+"° · vzdálenost: "+(distance/1000).toFixed(2)+" km";
  return;
 }
 const d=grid.distance[j],ft=Number($("inspection-level").value),target=ft*.3048;
 const samples=grid.terrain[i].slice(0,j+1),ranges=grid.distance.slice(0,j+1);
 const status=grid.status[String(ft)][i][j],ground=grid.terrain[i][j];
 const horizon=grid.lower[i][j],ceiling=grid.upper[i][j];
 const angle=Math.atan2((6371008.8*grid.k+target)*Math.cos(d/(6371008.8*grid.k))-(6371008.8*grid.k+grid.antenna),
   (6371008.8*grid.k+target)*Math.sin(d/(6371008.8*grid.k)))*180/Math.PI;
 let maxAngle=-Infinity,blocker=-1;
 for(let n=0;n<samples.length;n++){
  const z=samples[n],x=ranges[n];if(!Number.isFinite(z))continue;
  const q=Math.atan2((6371008.8*grid.k+z)*Math.cos(x/(6371008.8*grid.k))-(6371008.8*grid.k+grid.antenna),
   (6371008.8*grid.k+z)*Math.sin(x/(6371008.8*grid.k)))*180/Math.PI;
  if(q>maxAngle){maxAngle=q;blocker=n}
 }
 let causes=[];
 if(status===2)causes.push("Neúplná data DEM na trase – neznámé krytí");
 else if(status===0){
  if(target<ground)causes.push("Cíl pod úrovní místního terénu");
  if(target<horizon-1e-5)causes.push("Terénní stín / překážka");
  if(angle<grid.minElev-1e-5||angle>grid.maxElev+1e-5)causes.push("Mimo elevační rozsah");
  if(!causes.length)causes.push("Dosahový limit anténního diagramu / RF bilance / zadaná překážka");
 }
 const textStatus=status===2?"NEZNÁMÉ":status===1?"KRYTÝ":"NEKRYTÝ";
 const native=wgs84Destination(radarCenter[0],radarCenter[1],grid.az[i],d);
 if(inspectionLine)map.removeLayer(inspectionLine);
 if(inspectionMarker)map.removeLayer(inspectionMarker);
 inspectionLine=L.polyline([radarCenter,native],{color:"#fcbd67",weight:3,dashArray:"6,5",interactive:false}).addTo(map);
 inspectionMarker=L.circleMarker(native,{radius:7,color:"#fff",fillColor:status===1?"#1acb92":status===0?"#fa646d":"#e5ad54",fillOpacity:1,weight:2}).addTo(map);
 $("inspection").hidden=false;
 $("inspection-result").textContent=textStatus+" · "+ft+" ft AMSL"+(causes.length?"\n"+causes.join(" · "):"");
 $("inspection-details").textContent=
  "Kliknutý bod: "+selectedPoint.lat.toFixed(6)+"°, "+selectedPoint.lng.toFixed(6)+"°\n"+
  "Výpočetní vzorek: "+native[0].toFixed(6)+"°, "+native[1].toFixed(6)+"°\n"+
  "Azimut: "+(grid.az[i]%360+360)%360+"° · horizontální vzdálenost: "+(d/1000).toFixed(3)+" km\n"+
  "Výška antény: "+grid.antenna.toFixed(1)+" m AMSL · cíl: "+target.toFixed(1)+" m AMSL\n"+
  "Terén v cíli: "+(Number.isFinite(ground)?ground.toFixed(1):"N/A")+" m AMSL\n"+
  "Minimální potřebná výška pro LOS: "+(Number.isFinite(horizon)?horizon.toFixed(1):"N/A")+" m AMSL\n"+
  "Maximální geometrická výška: "+(Number.isFinite(ceiling)?ceiling.toFixed(1):"N/A")+" m AMSL\n"+
  "Elevace cíle: "+angle.toFixed(3)+"° · překážkový horizont: "+(Number.isFinite(maxAngle)?maxAngle.toFixed(3):"N/A")+"°\n"+
  "Limitní terén: "+(blocker>=0?(ranges[blocker]/1000).toFixed(3)+" km / "+samples[blocker].toFixed(1)+" m AMSL":"N/A")+"\n"+
  "Model Země: R = 6371008,8 m × k "+grid.k+" · krok azimutu a vzdálenosti je diskrétní.\n"+
  "Závěr pochází přímo z masky krytí EDITORU; profil z původních vzorků DEM.";
 drawProfile(ranges,samples,d,target);
}
function drawProfile(ranges,terrain,d,target){
 const svg=$("inspection-profile");svg.replaceChildren();
 const finite=terrain.filter(Number.isFinite);
 if(!finite.length)return;
 const min=Math.min(...finite,grid.antenna,target)-40,max=Math.max(...finite,grid.antenna,target)+40;
 const x=v=>26+v/d*475,y=v=>166-(v-min)/(max-min)*144;
 function poly(points,color,width,dash=""){const e=document.createElementNS("http://www.w3.org/2000/svg","polyline");
 e.setAttribute("points",points.map(p=>p.map(v=>v.toFixed(1)).join(",")).join(" "));e.setAttribute("fill","none");e.setAttribute("stroke",color);e.setAttribute("stroke-width",width);
 if(dash)e.setAttribute("stroke-dasharray",dash);svg.append(e)}
 let segment=[];
 terrain.forEach((z,i)=>{if(Number.isFinite(z))segment.push([x(ranges[i]),y(z)]);
 else if(segment.length){poly(segment,"#63d9b0",2);segment=[]}});
 if(segment.length)poly(segment,"#63d9b0",2);
 const re=6371008.8*grid.k;
 const angle=Math.atan2((re+target)*Math.cos(d/re)-(re+grid.antenna),(re+target)*Math.sin(d/re));
 // Exact same effective-Earth apparent angle and inverse height-at-angle as radar_core.
 const ray=ranges.map(v=>[x(v),y((re+grid.antenna)*Math.cos(angle)/Math.cos(v/re+angle)-re)]);
 poly([[x(0),y(grid.antenna)],...ray],"#ffbc63",2,"5,4");
 const txt=document.createElementNS("http://www.w3.org/2000/svg","text");
 txt.setAttribute("x",30);txt.setAttribute("y",14);txt.setAttribute("fill","#cde6f6");txt.setAttribute("font-size","11");
 txt.textContent="DEM (zelená) · LOS paprsek (oranžová) · "+(d/1000).toFixed(2)+" km";svg.append(txt)
}
function setup(){
 if(!window.L){status("Leaflet se nepodařilo načíst. Zkontroluj připojení nebo blokování CDN.");return}
 map=L.map("map",{center:radarCenter,zoom:7,preferCanvas:true,zoomControl:false,
   zoomAnimation:false,fadeAnimation:false,attributionControl:true});
 vectorRenderer=L.canvas({padding:.5});
 L.control.zoom({position:"topright"}).addTo(map);L.control.scale({position:"bottomright",imperial:false}).addTo(map);
 selectBase("dark");
 for(const [name,features] of Object.entries(DATA.layers||{}))addLayer(name,features,DATA.styles?.[name],false);
 refreshList();syncAll();fitAll();$("range-center").textContent="Radar: "+radarCenter.map(x=>Number(x).toFixed(6)+"°").join(" / ");
 loadDiagnostics();
 $("inspect").onclick=()=>{
  if(!grid){notify("Pro analýzu otevři VIEWER z vypočteného projektu EDITORU.",true);return}
  inspectEnabled=!inspectEnabled;$("inspect").setAttribute("aria-pressed",String(inspectEnabled));
  $("inspect").classList.toggle("primary",inspectEnabled);
  map.getContainer().style.cursor=inspectEnabled?"crosshair":"";
  if(inspectEnabled){$("inspection").hidden=false;$("inspection-result").textContent="Klikni do mapy pro výběr bodu."}
 };
 map.on("click",e=>{if(inspectEnabled&&grid){selectedPoint=e.latlng;showInspection()}});
 $("inspection-close").onclick=()=>{$("inspection").hidden=true;inspectEnabled=false;$("inspect").classList.remove("primary");$("inspect").setAttribute("aria-pressed","false");map.getContainer().style.cursor=""};
 $("go3d").hidden=!DATA.threeDUrl;
 $("go3d").onclick=()=>window.open(DATA.threeDUrl,"_blank","noopener");
 $("print-studio").onclick=()=>window.open(DATA.studioUrl,"_blank","noopener");
 $("panel-toggle").onclick=()=>{const hidden=$("panel").classList.toggle("hidden");$("panel-toggle").setAttribute("aria-expanded",String(!hidden));map.invalidateSize()};
 $("close").onclick=()=>{$("panel").classList.add("hidden");$("panel-toggle").setAttribute("aria-expanded","false")};
 $("fit").onclick=fitAll;
 $("quick-open").onclick=$("load").onclick=()=>{$("file").value="";$("file").click()};
 $("file").onchange=e=>importFiles(e.target.files);
 document.querySelectorAll("[data-tab]").forEach(btn=>btn.onclick=()=>{
   document.querySelectorAll("[data-tab]").forEach(b=>b.classList.toggle("active",b===btn));
   document.querySelectorAll(".section").forEach(s=>s.hidden=s.id!=="tab-"+btn.dataset.tab)
 });
 $("search").oninput=refreshList;
 $("all").onclick=()=>{for(const o of layers.values())o.style.show=true;refreshList();syncAll()};
 $("none").onclick=()=>{for(const o of layers.values())o.style.show=false;refreshList();syncAll()};
 $("invert").onclick=()=>{for(const o of layers.values())o.style.show=!o.style.show;refreshList();syncAll()};
 $("clear").onclick=()=>{if(!confirm("Odstranit všechny načtené vrstvy?"))return;resetLayers();refreshList();refreshLegend();notify("Vrstvy odstraněny")};
 $("base").onchange=e=>selectBase(e.target.value);
 $("labels").onchange=e=>{setting.labels=e.target.checked;for(const o of layers.values())if(o.geo)o.geo.eachLayer(l=>{
   if(l.getTooltip())l.getTooltip().options.opacity=setting.labels?1:0
 })};
 $("legend").onchange=e=>{setting.legend=e.target.checked;refreshLegend()};
 $("range-on").onchange=e=>{setting.range=e.target.checked;updateRange()};
 $("range").oninput=updateRange;
 $("save-geo").onclick=saveGeo;$("save-project").onclick=()=>saveCDView().catch(e=>notify(e.message,true));
 let dragDepth=0;
 document.addEventListener("dragenter",e=>{e.preventDefault();dragDepth++;$("drop").classList.add("on")});
 document.addEventListener("dragleave",e=>{e.preventDefault();if(--dragDepth<=0){dragDepth=0;$("drop").classList.remove("on")}});
 document.addEventListener("dragover",e=>e.preventDefault());
 document.addEventListener("drop",e=>{e.preventDefault();dragDepth=0;$("drop").classList.remove("on");importFiles(e.dataTransfer.files)});
 window.addEventListener("resize",()=>map.invalidateSize({pan:false,animate:false}));
 status(layers.size+" vrstev · mapový pracovní prostor připraven");
}
setup();
</script></body></html>"""
