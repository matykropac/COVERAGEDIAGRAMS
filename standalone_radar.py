"""Standalone Leaflet ADS-B display: no Streamlit map rerenders."""
import json
import math

import folium
import numpy as np
import streamlit as st
from folium.plugins import Fullscreen
from pyproj import Geod
from web_support import coverage_geojson
import radar_core as core

GEOD = Geod(ellps="WGS84")

def open_display(result, level_ft, provider, traffic=None):
    c = result["config"]
    m = folium.Map(location=[c.lat,c.lon], zoom_start=7, tiles="https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
                   attr="Tiles © Esri and its data providers",
                   control_scale=True, prefer_canvas=True)
    # Toggle each available calculated altitude slice independently.
    for flight_level in core.flight_levels_for(c.radar_mode):
        geo = coverage_geojson(result, flight_level)
        if not geo.get("features"):
            continue
        layer = folium.FeatureGroup(name=core.level_label(flight_level),
                                    show=flight_level == level_ft)
        folium.GeoJson(geo, style_function=lambda _:
                       {"color":"#12b9aa","weight":1,"fillColor":"#12b9aa",
                        "fillOpacity":0.22}).add_to(layer)
        layer.add_to(m)
    for nm in range(20,261,20):
        folium.Circle([c.lat,c.lon], radius=nm*1852, color="#8498ac",
                      weight=1, opacity=.65, fill=False,
                      tooltip=f"{nm} NM").add_to(m)
    folium.Marker([c.lat,c.lon],tooltip="RADAR",
                  icon=folium.Icon(color="orange",icon="signal")).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    Fullscreen(position="topright", title="Celá obrazovka", title_cancel="Zavřít fullscreen").add_to(m)
    # Keep the base map mounted; only update a dedicated aircraft layer.
    az = np.asarray(result["az"],dtype=float)
    dist = np.asarray(result["distance"],dtype=float)
    # Compact grid: ~1 NM radial spacing; preserve actual calculated limits.
    indexes = np.unique(np.clip(np.searchsorted(dist,np.arange(0,261)*1852),
                                0,len(dist)-1))
    lower = np.asarray(result["lower"])[:,indexes]
    upper = np.asarray(result["upper"])[:,indexes]
    known = np.asarray(result["known"])[:,indexes]
    def packed(a):
        return np.where(np.isfinite(a),np.round(a).astype(float),-99999).tolist()
    params = {"lat":c.lat,"lon":c.lon,"az":az.tolist(),
              "dist":dist[indexes].tolist(),"lower":packed(lower),
              "upper":packed(upper),"known":known.astype(int).tolist(),
              "provider":provider,"level":level_ft}
    mapname=m.get_name()
    script=r"""
(function(){
const cfg=__PARAMS__;
const map=__MAP__;
const nm=1852, rad=Math.PI/180;
const host={'ADSB.lol':'https://api.adsb.lol','Airplanes.live':'https://api.airplanes.live'}[cfg.provider];
const targets=L.layerGroup().addTo(map);
const history=new Map();
const title=document.createElement('div');
title.style.cssText='position:fixed;z-index:9999;left:12px;top:12px;background:#101e2ce8;color:white;padding:9px 14px;border-radius:7px;font:13px system-ui;pointer-events:none';
title.textContent='RADAR LIVE · connecting…';
document.body.appendChild(title);
const hav=(a,b,c,d)=>{let x=(c-a)*rad,y=(d-b)*rad,q=Math.sin(x/2)**2+Math.cos(a*rad)*Math.cos(c*rad)*Math.sin(y/2)**2;return 12742000*Math.asin(Math.min(1,Math.sqrt(q)));};
const bearing=(a,b,c,d)=>{let x=Math.sin((d-b)*rad)*Math.cos(c*rad),y=Math.cos(a*rad)*Math.sin(c*rad)-Math.sin(a*rad)*Math.cos(c*rad)*Math.cos((d-b)*rad);return (Math.atan2(x,y)/rad+360)%360;};
function classify(a){
 const alt=typeof a.alt_geom==='number'?a.alt_geom:a.alt_baro;
 if(typeof alt!=='number')return 'unknown';
 const d=hav(cfg.lat,cfg.lon,a.lat,a.lon), b=bearing(cfg.lat,cfg.lon,a.lat,a.lon);
 if(d>cfg.dist[cfg.dist.length-1])return 'hidden';
 let ai=0,delta=999;
 for(let i=0;i<cfg.az.length;i++){let z=Math.abs(((cfg.az[i]-b+540)%360)-180);if(z<delta){delta=z;ai=i;}}
 let ri=0;while(ri+1<cfg.dist.length&&cfg.dist[ri+1]<d)ri++;
 if(ri+1<cfg.dist.length&&Math.abs(cfg.dist[ri+1]-d)<Math.abs(cfg.dist[ri]-d))ri++;
 if(!cfg.known[ai][ri])return 'unknown';
 const h=alt*0.3048;
 return h>=cfg.lower[ai][ri]&&h<=cfg.upper[ai][ri]?'visible':'hidden';
}
const css=document.createElement('style');css.textContent='.aircraft-arrow{background:transparent;border:0}.aircraft-arrow svg{filter:drop-shadow(0 0 1px white)}';document.head.appendChild(css);
function update(ac){
 try{
  targets.clearLayers();
  const now=Date.now()/1000, seen=new Set();
  let count=0;
  for(const a of ac){
   if(typeof a.lat!=='number'||typeof a.lon!=='number'||!a.hex)continue;
   if(hav(cfg.lat,cfg.lon,a.lat,a.lon)>260*nm)continue;
   count++;seen.add(a.hex);
   const prev=history.get(a.hex)||[];
   if(prev.length&&hav(prev[prev.length-1][0],prev[prev.length-1][1],a.lat,a.lon)>15*nm)prev.length=0;
   if(!prev.length||hav(prev[prev.length-1][0],prev[prev.length-1][1],a.lat,a.lon)>15)prev.push([a.lat,a.lon,now]);
   else prev[prev.length-1][2]=now;
   let sum=0,cut=0;
   for(let i=prev.length-1;i>0;i--){sum+=hav(prev[i][0],prev[i][1],prev[i-1][0],prev[i-1][1]);if(sum>40*nm){cut=i;break;}}
   if(cut)prev.splice(0,cut);
   if(prev.length>500)prev.splice(0,prev.length-500);
   history.set(a.hex,prev);
   for(let i=1;i<prev.length;i++){
     L.polyline([prev[i-1].slice(0,2),prev[i].slice(0,2)],
       {color:'#000',weight:2,opacity:0.04+0.8*Math.pow(i/(prev.length-1),2),interactive:false}).addTo(targets);
   }
   const status=classify(a);
   const outline=status==='visible'?'#19e68c':status==='hidden'?'#ff405a':'#ffc857';
   const track=typeof a.track==='number'?a.track:0;
   const svg='<div style="width:14px;height:14px;transform:rotate('+track+'deg)"><svg width="14" height="14" viewBox="0 0 20 20"><path d="M10 1 L17 18 L10 14 L3 18 Z" fill="black" stroke="'+outline+'" stroke-width="2.7"/></svg></div>';
   const icon=L.divIcon({html:svg,className:'aircraft-arrow',iconSize:[14,14],iconAnchor:[7,7]});
   const callsign=(a.flight||a.hex).trim(), alt=typeof a.alt_geom==='number'?a.alt_geom:a.alt_baro;
   const popup=document.createElement('div');
   popup.textContent=callsign+' · '+(status==='visible'?'V KRYTÍ':status==='hidden'?'MIMO KRYTÍ':'NEURČENO')+' · '+(typeof alt==='number'?alt+' ft':'N/A')+' · '+(hav(cfg.lat,cfg.lon,a.lat,a.lon)/nm).toFixed(1)+' NM';
   L.marker([a.lat,a.lon],{icon}).bindTooltip(callsign).bindPopup(popup).addTo(targets);
  }
  for(const [id,pts] of history){if(!seen.has(id)&&now-pts[pts.length-1][2]>180)history.delete(id);}
  title.textContent='RADAR LIVE · '+cfg.provider+' · '+count+' targets · zelená: v krytí / červená: mimo / žlutá: neurčeno · '+new Date().toLocaleTimeString()+' · 5 s';
 }catch(err){title.textContent='ADS-B connection: '+err.message+' · retry 5 s';}
}
window.addEventListener('message',event=>{if(event.data?.type==='radar-targets')update(event.data.aircraft||[]);});
window.parent.postMessage({type:'radar-ready'},'*');
})();
""".replace("__PARAMS__",json.dumps(params,separators=(',',':'))).replace("__MAP__",mapname)
    # Folium's root.script children are rendered BEFORE its own map setup.
    # Appending our JS there causes a ReferenceError and an empty display.
    # Insert after Folium's initialization, inside the final script element.
    html = m.get_root().render()
    end = html.rfind("</script>")
    if end < 0:
        raise RuntimeError("Folium did not render a map initialization script")
    html = html[:end] + "\n" + script + "\n" + html[end:]
    radar_component = st.components.v2.component(
        name="persistent_radar_v2",
        html='<iframe class="radar-map" style="width:100%;height:850px;border:0" sandbox="allow-scripts allow-same-origin"></iframe>',
        js="""
export default function(component) {
 const frame=component.parentElement.querySelector('.radar-map');
 const data=component.data||{};
 if(!frame.dataset.initialized) {
   frame.dataset.initialized='yes';
   frame.srcdoc=data.html;
   frame.addEventListener('load',()=>frame.contentWindow.postMessage(
     {type:'radar-targets',aircraft:frame._latest||[]},'*'));
   window.addEventListener('message',event=>{
     if(event.source===frame.contentWindow&&event.data?.type==='radar-ready')
       frame.contentWindow.postMessage({type:'radar-targets',aircraft:frame._latest||[]},'*');
   });
 }
 frame._latest=data.aircraft||[];
 if(frame.contentWindow)frame.contentWindow.postMessage(
   {type:'radar-targets',aircraft:frame._latest},'*');
}
""")
    radar_component(key="radar_persistent", data={"html":html,"aircraft":traffic or []})
