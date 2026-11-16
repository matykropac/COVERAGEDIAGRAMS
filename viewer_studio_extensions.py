"""Optional, presentation-only controls for the fullscreen VIEWER.

Injected into the existing HTML after the original Leaflet setup. Keeps source
GeoJSON, radar calculations and existing viewer handlers unchanged.
"""
from __future__ import annotations

CONTROLS = """
<div class="field"><label for="studio-preset">Preset vrstev</label><select id="studio-preset"><option value="">Vyber…</option><option value="technical">Technical</option><option value="presentation">Presentation</option><option value="monochrome">Monochrome</option><option value="altitude">FL Spectrum</option></select></div>
<div class="field"><label for="studio-fl-speed">FL animace</label><select id="studio-fl-speed"><option value="1500">Pomalá</option><option value="800" selected>Normální</option><option value="350">Rychlá</option></select></div>
<div class="muted" id="studio-fl-state">Animace vypnutá</div>
<div class="note" id="studio-area">Plocha polygonů</div>
"""
MAP_CONTROLS = """
<h3>ULOŽENÉ POHLEDY</h3><select id="studio-views" class="wide"></select>
<div class="actions"><button id="studio-save">＋ Uložit</button><button id="studio-restore">↺ Obnovit</button></div>
<div class="muted">Pouze styly a kamera mapy; neukládají se geodata.</div>
"""
SCRIPT = r"""
// VIEWER Studio enhancements. Executed after the original setup() call.
// This module never writes to source feature geometries.
const studioSnapshotsKey="cdviewer:views:v2";
const studioAreaCache=new WeakMap();
let studioFLTimer=null,studioSavedVisibility=null,studioFLIndex=-1;
function hslToHex(h,s,l){
 s/=100;l/=100;
 const a=s*Math.min(l,1-l);
 const f=n=>{const k=(n+h/30)%12;
  return Math.round(255*(l-a*Math.max(-1,Math.min(k-3,9-k,1))))};
 return "#"+[f(0),f(8),f(4)].map(x=>x.toString(16).padStart(2,"0")).join("");
}
function studioApplyPreset(name){
 if(name==="altitude"){
  studioStopFL();
  const sorted=[...layers.values()].map(o=>({o,ft:selectedCoverageLevel(o.name)}))
   .filter(x=>x.ft!==null).sort((a,b)=>a.ft-b.ft);
  if(!sorted.length){notify("Nenalezeny hladiny RADAR / ... ft",true);return}
  const low=sorted[0].ft,span=Math.max(1,sorted[sorted.length-1].ft-low);
  for(const item of sorted){
   const ratio=(item.ft-low)/span;
   const hue=210-190*ratio;
   const rgb=hslToHex(hue,90,52);
   item.o.style.color=rgb;item.o.style.opacity=.38;syncOne(item.o);
  }
  refreshList();refreshLegend();notify("Použita barevná škála podle FL; data nezměněna");
  return;
 }
 const preset={
  technical:{opacity:.22,strokeOpacity:1,width:1.5,dash:"solid"},
  presentation:{opacity:.46,strokeOpacity:1,width:2.5,dash:"solid"},
  monochrome:{opacity:.18,strokeOpacity:1,width:1.7,dash:"solid",color:"#79bbdf"}
 }[name];
 if(!preset)return;
 studioStopFL();
 for(const o of layers.values()){Object.assign(o.style,preset);syncOne(o)}
 refreshList();refreshLegend();notify("Preset "+name+" aplikován pouze na vzhled.");
}
function studioMove(name,dir){
 const names=[...layers.keys()],i=names.indexOf(name),j=i+dir;
 if(i<0||j<0||j>=names.length)return;
 [names[i],names[j]]=[names[j],names[i]];
 const previous=layers;
 layers=new Map(names.map(n=>[n,previous.get(n)]));
 studioRenderRows();studioBringToFront();refreshLegend();
}
function studioBringToFront(){
 for(const o of layers.values())if(o.geo&&map.hasLayer(o.geo))o.geo.bringToFront();
}
function studioRenderRows(){
 refreshList();
 for(const o of layers.values()){
  const list=$("layer-list");
  const rows=[...list.children];
  const row=rows.find(r=>r.querySelector(".name")?.textContent===o.name);
  if(!row)continue;
  if(row.querySelector(".studio-up"))continue;
  const up=document.createElement("button"),down=document.createElement("button");
  up.textContent="↑";down.textContent="↓";
  up.title="Posunout vrstvu nad následující";down.title="Posunout vrstvu pod předchozí";
  up.className="studio-up";down.className="studio-down";
  up.onclick=()=>studioMove(o.name,1);down.onclick=()=>studioMove(o.name,-1);
  row.insertBefore(up,row.lastElementChild);row.insertBefore(down,row.lastElementChild);
 }
}
// Spherical area approximation, removes inner rings, DOES NOT union overlaps.
function studioRingAreaKm2(r){
 if(!Array.isArray(r)||r.length<4)return 0;
 let sum=0;
 for(let i=0;i<r.length-1;i++){
  const p=r[i],q=r[i+1];if(!p||!q)continue;
  sum+=(q[0]-p[0])*Math.PI/180*
   (2+Math.sin(p[1]*Math.PI/180)+Math.sin(q[1]*Math.PI/180));
 }
 return Math.abs(sum)*6371.0088*6371.0088/2;
}
function studioPolygonAreaKm2(p){
 return p?.length?Math.max(0,studioRingAreaKm2(p[0])-
  p.slice(1).reduce((a,r)=>a+studioRingAreaKm2(r),0)):0;
}
function studioGeometryAreaKm2(g){
 if(!g)return 0;
 if(g.type==="Polygon")return studioPolygonAreaKm2(g.coordinates);
 if(g.type==="MultiPolygon")return g.coordinates.reduce((a,p)=>a+studioPolygonAreaKm2(p),0);
 if(g.type==="GeometryCollection")return (g.geometries||[]).reduce((a,v)=>a+studioGeometryAreaKm2(v),0);
 return 0;
}
function studioUpdateArea(){
 let total=0;const lines=[];
 for(const o of layers.values())if(o.style.show){
  let a=studioAreaCache.get(o);
  if(a===undefined){a=o.features.reduce((n,f)=>n+studioGeometryAreaKm2(f.geometry),0);studioAreaCache.set(o,a)}
  if(a>0){total+=a;lines.push(o.name+": "+a.toFixed(1)+" km²")}
 }
 $("studio-area").textContent="Součet ploch polygonů: "+total.toFixed(1)+" km²\n"+
  lines.slice(0,10).join("\n")+"\nOrientační výpočet z původních geometrií; překryvy se neodečítají.";
}
function studioStopFL(){
 if(studioFLTimer!==null){clearInterval(studioFLTimer);studioFLTimer=null}
 if(studioSavedVisibility){
  for(const [name,visible] of studioSavedVisibility)if(layers.has(name))
   layers.get(name).style.show=visible;
  studioSavedVisibility=null;refreshList();syncAll();
 }
 $("studio-fl-button").textContent="▶ FL";
 $("studio-fl-state").textContent="Animace vypnutá";
}
function studioStepFL(){
 const eligible=[...layers.values()].map(o=>({o,ft:selectedCoverageLevel(o.name)}))
  .filter(v=>v.ft!==null);
 const levels=[...new Set(eligible.map(v=>v.ft))].sort((a,b)=>a-b);
 if(!levels.length){studioStopFL();return}
 studioFLIndex=(studioFLIndex+1)%levels.length;const ft=levels[studioFLIndex];
 for(const v of eligible)v.o.style.show=(v.ft===ft);
 refreshList();syncAll();
 $("studio-fl-state").textContent="FL "+ft.toLocaleString("cs")+" ft AMSL";
}
function studioToggleFL(){
 if(studioFLTimer!==null){studioStopFL();return}
 if(![...layers.keys()].some(n=>selectedCoverageLevel(n)!==null)){
  notify("Chybí vrstvy typu RADAR / ... ft",true);return;
 }
 studioSavedVisibility=new Map([...layers].map(([n,o])=>[n,o.style.show]));
 studioFLIndex=-1;studioStepFL();
 studioFLTimer=setInterval(studioStepFL,Number($("studio-fl-speed").value));
 $("studio-fl-button").textContent="■ FL";
}
function studioReadViews(){
 try{const v=JSON.parse(localStorage.getItem(studioSnapshotsKey)||"[]");
  return Array.isArray(v)?v.slice(0,20):[]}catch(e){return []}
}
function studioRefreshViews(){
 const el=$("studio-views");el.replaceChildren();
 for(const v of studioReadViews()){const o=document.createElement("option");
  o.textContent=v.name;o.value=v.id;el.append(o)}
}
function studioSaveView(){
 const name=prompt("Název mapového pohledu","Radar "+new Date().toLocaleString("cs"));
 if(!name)return;
 const view={id:String(Date.now()),name:name.slice(0,90),base:setting.base,
  center:[map.getCenter().lat,map.getCenter().lng],zoom:map.getZoom(),
  order:[...layers.keys()],
  styles:Object.fromEntries([...layers].map(([n,o])=>[n,{...o.style}]))};
 try{localStorage.setItem(studioSnapshotsKey,JSON.stringify([view,...studioReadViews()].slice(0,20)));
  studioRefreshViews();$("studio-views").value=view.id;notify("Pohled uložen lokálně, bez geodat.")}
 catch(e){notify("Uložení pohledu selhalo: "+e.message,true)}
}
function studioRestoreView(){
 const v=studioReadViews().find(x=>x.id===$("studio-views").value);if(!v)return;
 studioStopFL();
 if(BASES[v.base])selectBase(v.base);
 for(const [name,style] of Object.entries(v.styles||{})){
  if(layers.has(name))layers.get(name).style=initialStyle(style,0);
 }
 if(Array.isArray(v.order)){
  const order=v.order.filter(n=>layers.has(n));
  for(const n of layers.keys())if(!order.includes(n))order.push(n);
  layers=new Map(order.map(n=>[n,layers.get(n)]));
 }
 refreshList();syncAll();studioBringToFront();studioRenderRows();
 if(Array.isArray(v.center)&&v.center.length===2&&Number.isFinite(v.zoom))
  map.setView(v.center,v.zoom,{animate:false});
 notify("Obnoven pohled: "+v.name);
}
// Preserve original entrypoints, including the existing editor drawer and diagnostics.
const studioOldRefreshList=refreshList;
refreshList=function(){studioOldRefreshList();studioRenderRowButtons()};
function studioRenderRowButtons(){
 for(const row of $("layer-list").children){
  if(row.querySelector(".studio-up"))continue;
  const name=row.querySelector(".name")?.textContent;
  if(!name||!layers.has(name))continue;
  const up=document.createElement("button"),down=document.createElement("button");
  up.textContent="↑";down.textContent="↓";up.title="Vrstva výše";down.title="Vrstva níže";
  up.className="studio-up";down.className="studio-down";
  up.onclick=()=>studioMove(name,1);down.onclick=()=>studioMove(name,-1);
  row.insertBefore(up,row.lastElementChild);row.insertBefore(down,row.lastElementChild);
 }
}
const studioOldSyncAll=syncAll;
syncAll=function(){studioOldSyncAll();studioBringToFront();studioUpdateArea()};
const studioOldSyncOne=syncOne;
syncOne=function(o){studioOldSyncOne(o);studioUpdateArea()};
$("studio-preset").onchange=e=>{studioApplyPreset(e.target.value);e.target.value=""};
$("studio-fl-button").onclick=studioToggleFL;
$("studio-fl-speed").onchange=()=>{if(studioFLTimer!==null){
 clearInterval(studioFLTimer);studioFLTimer=setInterval(studioStepFL,Number($("studio-fl-speed").value))}};
$("studio-save").onclick=studioSaveView;$("studio-restore").onclick=studioRestoreView;
const studioOldReset=resetLayers;
resetLayers=function(){studioStopFL();studioOldReset()};
studioRenderRowButtons();studioRefreshViews();studioUpdateArea();
"""


def enhance_page(page: str) -> str:
    """Inject once, using stable IDs rather than replacing existing handlers."""
    assert 'id="layer-stats"' in page
    assert 'id="range-center"' in page
    assert 'setup();' in page
    page = page.replace('<div class="muted" id="layer-stats"></div>',
                        CONTROLS + '<div class="muted" id="layer-stats"></div>', 1)
    page = page.replace('<div class="muted" id="range-center">Střed: radar</div>',
                        '<div class="muted" id="range-center">Střed: radar</div>'+MAP_CONTROLS,1)
    page = page.replace('<button id="fit" class="ghost">◎ Přiblížit data</button>',
                        '<button id="fit" class="ghost">◎ Přiblížit data</button>'
                        '<button id="studio-fl-button" class="ghost">▶ FL</button>',1)
    page = page.replace('setup();\n</script></body></html>',
                        'setup();\n' + SCRIPT + '\n' + CARTOGRAPHY_SCRIPT + '\n</script></body></html>',1)
    page = page.replace('grid-template-columns:19px 1fr 31px',
                        'grid-template-columns:19px minmax(0,1fr) 25px 25px 31px',1)
    page = page.replace('<div class="muted" id="range-center">Střed: radar</div>',
                        '<div class="muted" id="range-center">Střed: radar</div>'+CARTOGRAPHY_CONTROLS,1)
    return page


CARTOGRAPHY_CONTROLS = """
<h3>KARTOGRAFICKÉ NÁSTROJE</h3>
<div class="actions"><button id="studio-measure">⌖ MĚŘIT</button><button id="studio-annotate">✎ POPISEK</button></div>
<div id="studio-measure-result" class="note">Klikni MĚŘIT a pak na dva body v mapě.</div>
<div class="field"><label for="studio-graticule">Mřížka LAT/LON</label><input type="checkbox" id="studio-graticule"></div>
<div class="actions"><button id="studio-clear-measure">Vymazat měření</button><button id="studio-export-notes">⇩ Popisky GeoJSON</button></div>
<div class="field"><label for="studio-vector-only">Bez online podkladu</label><input id="studio-vector-only" type="checkbox"></div>
<div class="field"><label for="studio-offline-zip">Offline dlaždice ZIP</label><input id="studio-offline-zip" type="file" accept=".zip,application/zip"></div>
<div class="actions"><button id="studio-offline-clear">Vypnout offline dlaždice</button></div>
<div class="muted">Vlastní XYZ mapové dlaždice v ZIP: z/x/y.png nebo .jpg. Max. 180 MB. Data zůstávají v prohlížeči.</div>
<h3>INSPECTOR · PŮVODNÍ POLYGONY</h3><div id="studio-hit-result" class="note">Klikni do mapy pro kontrolu příslušnosti k původním vrstvám.</div>
<div class="muted">Režim bez dlaždic nevytváří kompletní offline aplikaci. Leaflet/JSZip se stále načítají z CDN, pokud nejsou v cache.</div>
"""

CARTOGRAPHY_SCRIPT = r"""
// Cartography overlays are never incorporated into source radar coverage layers.
let cartoMode=null,cartoPoints=[],cartoMeasureShape=null,cartoLabels=[],cartoGrid=null;
let cartoOldBase="hillshade";
const cartoToRad=d=>d*Math.PI/180;
function cartoInverse(a,b){
 const p1=cartoToRad(a.lat),p2=cartoToRad(b.lat);
 const dl=cartoToRad(b.lng-a.lng),dp=p2-p1;
 const h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
 const distance=2*6371008.8*Math.asin(Math.min(1,Math.sqrt(h)));
 const y=Math.sin(dl)*Math.cos(p2);
 const x=Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl);
 return {km:distance/1000,nm:distance/1852,az:(Math.atan2(y,x)*180/Math.PI+360)%360};
}
function cartoStop(){
 cartoMode=null;$("studio-measure").classList.remove("primary");
 $("studio-annotate").classList.remove("primary");map.getContainer().style.cursor="";
}
function cartoChoose(mode){
 if(cartoMode===mode){cartoStop();return}
 inspectEnabled=false;$("inspect").classList.remove("primary");
 $("inspect").setAttribute("aria-pressed","false");
 cartoMode=mode;cartoPoints=[];
 $("studio-measure").classList.toggle("primary",mode==="measure");
 $("studio-annotate").classList.toggle("primary",mode==="annotate");
 map.getContainer().style.cursor="crosshair";
 $("studio-measure-result").textContent=mode==="measure"?"Vyber první a druhý bod na mapě.":
  "Klikni na místo, kam chceš umístit popisek.";
}
function cartoOnClick(e){
 if(!cartoMode)return;
 if(cartoMode==="annotate"){
  const label=prompt("Text popisku (max 140 znaků)","");
  if(label){
   const text=label.trim().slice(0,140);
   if(text){
    const f={type:"Feature",geometry:{type:"Point",coordinates:[e.latlng.lng,e.latlng.lat]},
      properties:{name:text,annotation:true}};
    const m=L.marker(e.latlng,{draggable:true}).addTo(map);
    m.bindTooltip(escapeHTML(text),{permanent:true,direction:"top"}).openTooltip();
    cartoLabels.push({marker:m,feature:f});
   }
  }
  cartoStop();return;
 }
 cartoPoints.push(e.latlng);
 if(cartoPoints.length===2){
  if(cartoMeasureShape)map.removeLayer(cartoMeasureShape);
  cartoMeasureShape=L.polyline(cartoPoints,{color:"#f6b95f",weight:3,dashArray:"5 5"}).addTo(map);
  const data=cartoInverse(cartoPoints[0],cartoPoints[1]);
  $("studio-measure-result").textContent=data.km.toFixed(3)+" km / "+data.nm.toFixed(3)+
    " NM · azimut "+data.az.toFixed(2)+"° (sférická aproximace)";
  cartoStop();
 }
}
function cartoGridUpdate(){
 if(cartoGrid){map.removeLayer(cartoGrid);cartoGrid=null}
 if(!$("studio-graticule").checked)return;
 const b=map.getBounds(),sw=b.getSouthWest(),ne=b.getNorthEast();
 const latMin=Math.max(-85,sw.lat),latMax=Math.min(85,ne.lat);
 const lonMin=Math.max(-180,sw.lng),lonMax=Math.min(180,ne.lng);
 if(latMax<=latMin||lonMax<=lonMin)return;
 const span=Math.max(latMax-latMin,lonMax-lonMin);
 const inc=span>50?10:span>10?2:span>2?.5:span>.5?.1:span>.1?.02:.005;
 const lines=[];
 for(let lat=Math.ceil(latMin/inc)*inc;lat<=latMax&&lines.length<45;lat+=inc)
  lines.push([[lat,lonMin],[lat,lonMax]]);
 for(let lon=Math.ceil(lonMin/inc)*inc;lon<=lonMax&&lines.length<90;lon+=inc)
  lines.push([[latMin,lon],[latMax,lon]]);
 cartoGrid=L.layerGroup(lines.map(coords=>L.polyline(coords,
  {color:"#9cbbcd",opacity:.42,weight:.7,interactive:false}))).addTo(map);
}
$("studio-measure").onclick=()=>cartoChoose("measure");
$("studio-annotate").onclick=()=>cartoChoose("annotate");
map.on("click",cartoOnClick);
$("studio-clear-measure").onclick=()=>{
 cartoPoints=[];if(cartoMeasureShape){map.removeLayer(cartoMeasureShape);cartoMeasureShape=null}
 $("studio-measure-result").textContent="Měření odstraněno.";cartoStop();
};
$("studio-graticule").onchange=cartoGridUpdate;
map.on("moveend",cartoGridUpdate);
$("studio-export-notes").onclick=()=>{
 const features=cartoLabels.map(x=>({...x.feature,
   geometry:{type:"Point",coordinates:[x.marker.getLatLng().lng,x.marker.getLatLng().lat]}}));
 download("VIEWER_Annotations.geojson",new Blob([JSON.stringify(
  {type:"FeatureCollection",features})],{type:"application/geo+json"}));
};

// Native polygon membership inspector: presentation smoothing is ignored.
function cartoPointInRing(lon,lat,ring){
 let inside=false;
 if(!Array.isArray(ring))return false;
 for(let i=0,j=ring.length-1;i<ring.length;j=i++){
  const a=ring[i],b=ring[j];if(!a||!b)continue;
  const crosses=(a[1]>lat)!==(b[1]>lat);
  const x=(b[0]-a[0])*(lat-a[1])/((b[1]-a[1])||1e-30)+a[0];
  if(crosses&&lon<x)inside=!inside;
 }
 return inside;
}
function cartoPointInGeometry(lon,lat,g){
 if(!g)return false;
 const poly=p=>Array.isArray(p)&&p.length&&cartoPointInRing(lon,lat,p[0])&&
  !p.slice(1).some(r=>cartoPointInRing(lon,lat,r));
 if(g.type==="Polygon")return poly(g.coordinates);
 if(g.type==="MultiPolygon")return (g.coordinates||[]).some(poly);
 if(g.type==="GeometryCollection")return (g.geometries||[]).some(x=>cartoPointInGeometry(lon,lat,x));
 return false;
}
map.on("click",e=>{
 const hits=[];
 for(const o of layers.values()){
  if(!o.style.show)continue;
  if(o.features.some(f=>cartoPointInGeometry(e.latlng.lng,e.latlng.lat,f.geometry)))hits.push(o.name);
 }
 $("studio-hit-result").textContent="Původní polygon v místě "+e.latlng.lat.toFixed(5)+"°, "+
  e.latlng.lng.toFixed(5)+"°:\\n"+(hits.length?hits.slice(0,15).join("\\n"):
  "Bod neleží uvnitř žádné viditelné polygonové vrstvy.")+
  "\\nJde pouze o prostorový test polygonů, nikoli potvrzení RF detekce.";
});


// Optional user-supplied XYZ tiles from ZIP. No tile server or upload.
let cartoOfflineLayer=null,cartoOfflineZip=null,cartoBeforeOffline="hillshade";
function cartoUnsetOffline(){
 if(cartoOfflineLayer){map.removeLayer(cartoOfflineLayer);cartoOfflineLayer=null}
 cartoOfflineZip=null;
 $("studio-offline-zip").value="";
}
$("studio-offline-clear").onclick=()=>{
 cartoUnsetOffline();
 if($("studio-vector-only").checked){
  if(base)map.removeLayer(base);base=null;setting.base="vector-only";
 }else selectBase(BASES[cartoBeforeOffline]?cartoBeforeOffline:"hillshade");
 notify("Lokální mapové dlaždice byly uvolněny z paměti.");
};
$("base").addEventListener("change",()=>{
 if(cartoOfflineLayer)cartoUnsetOffline();
 $("studio-vector-only").checked=false;
});
$("studio-offline-zip").onchange=async e=>{
 const file=e.target.files?.[0];if(!file)return;
 if(file.size>180*1024*1024){notify("Offline ZIP překračuje limit 180 MB.",true);e.target.value="";return}
 if(!window.JSZip){notify("JSZip není dostupný.",true);return}
 try{
  const archive=await JSZip.loadAsync(file);
  const keys=Object.keys(archive.files);
  if(keys.length>90000)throw Error("Příliš mnoho dlaždic (max. 90 000).");
  const count=keys.filter(n=>/^(?:\d+\/){2}\d+\.(?:png|jpe?g|webp)$/i.test(n)).length;
  if(!count)throw Error("ZIP neobsahuje očekávané cesty z/x/y.png nebo .jpg.");
  cartoUnsetOffline();cartoBeforeOffline=BASES[setting.base]?setting.base:"hillshade";
  cartoOfflineZip=archive;
  const OfflineTiles=L.GridLayer.extend({
   createTile:function(coords,done){
    const tile=document.createElement("img");tile.alt="";
    tile.width=256;tile.height=256;
    const prefix=coords.z+"/"+coords.x+"/"+coords.y;
    let entry=null;
    for(const ext of [".png",".jpg",".jpeg",".webp"]){
     entry=cartoOfflineZip?.file(prefix+ext);if(entry)break;
    }
    if(!entry){tile.style.opacity="0";done(null,tile);return tile}
    entry.async("blob").then(blob=>{
     const url=URL.createObjectURL(blob);
     tile.onload=()=>{URL.revokeObjectURL(url);done(null,tile)};
     tile.onerror=()=>{URL.revokeObjectURL(url);done(null,tile)};
     tile.src=url;
    }).catch(error=>done(error,tile));
    return tile;
   }
  });
  if(base)map.removeLayer(base);base=null;
  cartoOfflineLayer=new OfflineTiles({tileSize:256,maxZoom:19,noWrap:true,attribution:"User-provided offline tiles"}).addTo(map);
  cartoOfflineLayer.bringToBack();
  setting.base="offline-tiles";
  $("studio-vector-only").checked=false;
  notify("Lokální XYZ dlaždice připraveny: "+count+" položek. Mapa nepoužívá síťové tile URL.");
 }catch(error){notify("Offline ZIP: "+error.message,true);cartoUnsetOffline()}
};

// No network tiles; this remains an online-app feature until Leaflet is packaged locally.
$("studio-vector-only").onchange=e=>{
 if(cartoOfflineLayer)cartoUnsetOffline();
 if(e.target.checked){
  cartoOldBase=setting.base;
  if(base)map.removeLayer(base);
  base=null;setting.base="vector-only";
  notify("Pouze vektory · podkladové dlaždice vypnuty.");
 }else selectBase(BASES[cartoOldBase]?cartoOldBase:"hillshade");
};
"""
