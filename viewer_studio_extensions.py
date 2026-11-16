"""Optional, presentation-only controls for the fullscreen VIEWER.

Injected into the existing HTML after the original Leaflet setup. Keeps source
GeoJSON, radar calculations and existing viewer handlers unchanged.
"""
from __future__ import annotations

CONTROLS = """
<div class="field"><label for="studio-preset">Preset vrstev</label><select id="studio-preset"><option value="">Vyber…</option><option value="technical">Technical</option><option value="presentation">Presentation</option><option value="monochrome">Monochrome</option></select></div>
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
let studioFLTimer=null,studioSavedVisibility=null,studioFLIndex=-1;
function studioApplyPreset(name){
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
  const a=o.features.reduce((n,f)=>n+studioGeometryAreaKm2(f.geometry),0);
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
                        'setup();\n' + SCRIPT + '\n</script></body></html>',1)
    page = page.replace('grid-template-columns:19px 1fr 31px',
                        'grid-template-columns:19px minmax(0,1fr) 25px 25px 31px',1)
    return page
