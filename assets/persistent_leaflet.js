const INSTANCES = new WeakMap();
const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const DRAW_CSS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css";
const DRAW_JS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js";

function stylesheet(url) {
  if (document.querySelector('link[data-cd-style="'+url+'"]')) return;
  const link=document.createElement("link");
  link.rel="stylesheet"; link.href=url;link.dataset.cdStyle=url;
  document.head.appendChild(link);
}
function script(url) {
  const existing=document.querySelector('script[data-cd-script="'+url+'"]');
  if (existing) return existing.cdReady;
  const elem=document.createElement("script");
  elem.dataset.cdScript=url;elem.src=url;elem.async=true;
  elem.cdReady=new Promise((resolve,reject)=>{
    elem.addEventListener("load",resolve,{once:true});
    elem.addEventListener("error",()=>reject(new Error("Nelze načíst mapovou knihovnu")),{once:true});
  });
  document.head.appendChild(elem);
  return elem.cdReady;
}
function resources() {
  if (!window.__cdLeafletReady) {
    stylesheet(LEAFLET_CSS);
    stylesheet(DRAW_CSS);
    window.__cdLeafletReady=script(LEAFLET_JS).then(()=>script(DRAW_JS));
  }
  return window.__cdLeafletReady;
}
const identical=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function status(s,message) {
  if(!s.badge)return;
  s.badge.textContent=message||"";
  s.badge.style.display=message?"block":"none";
}
function ensureBaseLayers(s, data) {
  const specs=data.basemaps||[];
  const list=JSON.stringify(specs);
  if (s.baseSignature===list)return;
  s.baseSignature=list;
  const oldName=s.activeBaseName||"OpenStreetMap";
  const next=new Map();
  for(const spec of specs){
    if(!spec.url||!spec.name)continue;
    const layer=L.tileLayer(spec.url,{attribution:spec.attribution||"",
      maxZoom:spec.max_zoom||19,crossOrigin:false});
    next.set(spec.name,layer);
  }
  const chosen=next.get(oldName)||next.get("OpenStreetMap")||next.values().next().value;
  for(const layer of s.baseLayers.values())s.map.removeLayer(layer);
  s.baseLayers=next;
  s.activeBaseName=[...next].find(([_,layer])=>layer===chosen)?.[0]||oldName;
  if(chosen)chosen.addTo(s.map);
  refreshControl(s);
}
function refreshControl(s) {
  if(s.controls.layers){s.map.removeControl(s.controls.layers);s.controls.layers=null;}
  const bases={};
  for(const [name,layer] of s.baseLayers) bases[name]=layer;
  const overlay={
    "Radarové krytí":s.groups.coverage,
    "Překážky":s.groups.obstacles,
    "Radar":s.groups.radar,
    "Další geodata":s.groups.environment,
    "ADS-B LIVE":s.groups.aircraft,
  };
  if(s.openaipLayer) overlay["OpenAIP · letecká mapa"]=s.openaipLayer;
  s.controls.layers=L.control.layers(bases,overlay,{collapsed:true,position:"topright"});
  s.controls.layers.addTo(s.map);
}
// Point inspection is deliberately browser-side: clicking the map must
// never cause a Streamlit rerun or recreate Leaflet/tile layers.
function geodesic(site, point){
  const rad=Math.PI/180;
  const p1=site[0]*rad,p2=point.lat*rad,dLat=(point.lat-site[0])*rad;
  const dLon=(point.lng-site[1])*rad;
  const h=Math.sin(dLat/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dLon/2)**2;
  const km=6371.0088*2*Math.asin(Math.min(1,Math.sqrt(h)));
  const y=Math.sin(dLon)*Math.cos(p2);
  const x=Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dLon);
  const az=(Math.atan2(y,x)/rad+360)%360;
  return {km,az};
}
function nearestAzimuth(values,az){
  let best=Infinity,idx=0;
  for(let i=0;i<values.length;i++){
    const delta=Math.abs(((az-values[i]+540)%360)-180);
    if(delta<best){best=delta;idx=i;}
  }
  return {idx,delta:best};
}
function nearestDistance(values,km){
  if(!values.length)return 0;
  let lo=0,hi=values.length-1;
  while(lo<hi){
    const mid=(lo+hi)>>1;
    if(values[mid]<km)lo=mid+1;else hi=mid;
  }
  return lo>0&&Math.abs(values[lo-1]-km)<Math.abs(values[lo]-km)?lo-1:lo;
}
function canvasText(ctx,txt,x,y,align="left",color="#60768a",size=11){
  ctx.fillStyle=color;ctx.textAlign=align;ctx.font=size+"px system-ui";
  ctx.fillText(txt,x,y);ctx.textAlign="left";
}
function drawTerrain(s){
  const panel=s.profilePanel,canvas=s.profileCanvas,sel=s.selection;
  const p=s.latest?.profile;
  if(!panel||!canvas||!sel||!p?.distance?.length||!p.terrain?.length)return;
  const width=Math.max(260,Math.round(canvas.getBoundingClientRect().width));
  const height=150,dpr=Math.min(2,window.devicePixelRatio||1);
  canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
  const ctx=canvas.getContext("2d");if(!ctx)return;
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  const profileAz=nearestAzimuth(p.az||[],sel.az);
  const terrain=p.terrain[profileAz.idx]||[];
  const lower=p.lower?.[profileAz.idx]||[];
  const dist=p.distance;
  const maxKm=Math.max(1,Number(p.maxRangeKm)||dist[dist.length-1]||1);
  const span=Math.max(8,Math.min(maxKm,Math.max(12,maxKm*.32)));
  // The selected point is always the center of the terrain window.
  const from=sel.km-span/2,to=sel.km+span/2;
  const left=52,right=width-18,top=13,bottom=height-30;
  const entries=[];
  for(let i=0;i<dist.length;i++){
    const d=dist[i];
    if(d<from||d>to)continue;
    const tr=terrain[i],lo=lower[i];
    if(Number.isFinite(tr))entries.push(tr);
    if(Number.isFinite(lo))entries.push(lo);
  }
  const x=d=>left+(d-from)/(to-from)*(right-left);
  if(!entries.length){
    canvasText(ctx,"Pro toto místo nejsou dostupná data terénu.",left,70);
    canvasText(ctx,from.toFixed(1)+" km",left,height-8);
    canvasText(ctx,to.toFixed(1)+" km",right,height-8,"right");
    return;
  }
  let min=Math.min(...entries),max=Math.max(...entries);
  const pad=Math.max(25,(max-min)*.15);min-=pad;max+=pad;
  const y=value=>bottom-(value-min)/(max-min)*(bottom-top);
  ctx.strokeStyle="#e5ecf3";ctx.lineWidth=1;
  for(let i=0;i<4;i++){
    const value=min+(max-min)*i/3,yy=y(value);
    ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(right,yy);ctx.stroke();
    canvasText(ctx,Math.round(value)+" m",left-7,yy+4,"right","#73869b",10);
  }
  ctx.save();ctx.beginPath();ctx.rect(left,top,right-left,bottom-top);ctx.clip();
  function path(values,color,lineWidth){
    ctx.beginPath();let started=false;
    for(let i=0;i<dist.length;i++){
      const v=values[i],d=dist[i];
      if(!Number.isFinite(v)){started=false;continue;}
      if(!started){ctx.moveTo(x(d),y(v));started=true;}else ctx.lineTo(x(d),y(v));
    }
    ctx.strokeStyle=color;ctx.lineWidth=lineWidth;ctx.lineJoin="round";ctx.stroke();
  }
  // Fill terrain under the plot as a subtle cartographic cross-section.
  ctx.beginPath();let started=false;
  for(let i=0;i<dist.length;i++){
    const v=terrain[i],d=dist[i];
    if(!Number.isFinite(v))continue;
    if(!started){ctx.moveTo(x(d),bottom);ctx.lineTo(x(d),y(v));started=true;}
    else ctx.lineTo(x(d),y(v));
  }
  if(started){ctx.lineTo(x(dist[dist.length-1]),bottom);ctx.closePath();
    ctx.fillStyle="rgba(20,157,178,.09)";ctx.fill();}
  path(terrain,"#139db2",2);
  path(lower,"#dd8841",1.7);
  const sx=x(sel.km);
  ctx.setLineDash([4,3]);ctx.beginPath();ctx.moveTo(sx,top);ctx.lineTo(sx,bottom);
  ctx.strokeStyle="#e34c57";ctx.lineWidth=1.3;ctx.stroke();ctx.setLineDash([]);
  const at=nearestDistance(dist,sel.km);
  if(Number.isFinite(terrain[at])){
    ctx.beginPath();ctx.arc(sx,y(terrain[at]),4.2,0,Math.PI*2);
    ctx.fillStyle="#e34c57";ctx.fill();ctx.strokeStyle="#fff";ctx.lineWidth=1.5;ctx.stroke();
  }
  ctx.restore();
  canvasText(ctx,from.toFixed(1)+" km",left,height-8);
  canvasText(ctx,sel.km.toFixed(2)+" km",sx,height-8,"center","#d45259",11);
  canvasText(ctx,to.toFixed(1)+" km",right,height-8,"right");
}
function terrainDestination(site,bearing,km){
  const rad=Math.PI/180,d=km/6371.0088,lat1=site[0]*rad,lon1=site[1]*rad,b=bearing*rad;
  const lat=Math.asin(Math.sin(lat1)*Math.cos(d)+Math.cos(lat1)*Math.sin(d)*Math.cos(b));
  const lon=lon1+Math.atan2(Math.sin(b)*Math.sin(d)*Math.cos(lat1),
    Math.cos(d)-Math.sin(lat1)*Math.sin(lat));
  return [lat/rad,((lon/rad+540)%360)-180];
}
function hideTerrainWedge(s){
  if(s.terrainWedge){s.map.removeLayer(s.terrainWedge);s.terrainWedge=null;}
}
function showTerrainWedge(s){
  hideTerrainWedge(s);
  const p=s.latest?.profile,sel=s.selection;
  if(!p?.distance?.length||!sel||sel.km<=0||!p.terrain?.length)return;
  const step=Math.max(1,Math.ceil(p.distance.length/65));
  const range=Math.min(sel.km,Number(p.maxRangeKm)||sel.km);
  const group=L.layerGroup();
  const cells=[];
  for(let delta=-10;delta<10;delta+=2){
    const a=(sel.az+delta+360)%360,b=(sel.az+delta+2+360)%360;
    const row=p.terrain[nearestAzimuth(p.az,(sel.az+delta+1+360)%360).idx]||[];
    for(let i=0;i<p.distance.length-1;i+=step){
      const j=Math.min(p.distance.length-1,i+step),lo=p.distance[i],hi=Math.min(range,p.distance[j]);
      if(lo>=range||hi<=lo)break;
      const h=row[Math.min(row.length-1,Math.floor((i+j)/2))];
      if(!Number.isFinite(h))continue;
      cells.push({a,b,lo,hi,h});
    }
  }
  if(!cells.length)return;
  const heights=cells.map(x=>x.h);
  const min=Math.min(...heights),max=Math.max(...heights),spread=Math.max(1,max-min);
  const palette=["#1e5b7c","#217d92","#4b9b83","#9bad75","#dbbb80"];
  for(const cell of cells){
    const idx=Math.min(palette.length-1,
      Math.max(0,Math.floor((cell.h-min)/spread*(palette.length-1))));
    L.polygon([
      terrainDestination(p.site,cell.a,cell.lo),
      terrainDestination(p.site,cell.b,cell.lo),
      terrainDestination(p.site,cell.b,cell.hi),
      terrainDestination(p.site,cell.a,cell.hi)
    ],{stroke:false,fillColor:palette[idx],fillOpacity:.62,
       interactive:false}).addTo(group);
  }
  group.addTo(s.map);
  s.terrainWedge=group;
  if(s.selectionLine)s.selectionLine.bringToFront();
  if(s.selectionMarker)s.selectionMarker.bringToFront();
}
function clearTerrainSelection(s){
  hideTerrainWedge(s);
  s.selection=null;
  if(s.selectionMarker){s.map.removeLayer(s.selectionMarker);s.selectionMarker=null;}
  if(s.selectionLine){s.map.removeLayer(s.selectionLine);s.selectionLine=null;}
  if(s.profilePanel)s.profilePanel.hidden=true;
}
function selectTerrainPoint(s,latlng){
  const p=s.latest?.profile;
  if(!p?.site||!p?.terrain?.length)return;
  const site=p.site;
  const {km,az}=geodesic(site,latlng);
  s.selection={lat:latlng.lat,lon:latlng.lng,km,az};
  hideTerrainWedge(s);
  if(s.selectionMarker)s.map.removeLayer(s.selectionMarker);
  if(s.selectionLine)s.map.removeLayer(s.selectionLine);
  s.selectionMarker=L.circleMarker(latlng,{radius:7,color:"#ffffff",
    weight:2,fillColor:"#e34c57",fillOpacity:1}).addTo(s.map);
  s.selectionLine=L.polyline([site,[latlng.lat,latlng.lng]],
    {color:"#e34c57",weight:3,dashArray:"6 5",opacity:.94,
     interactive:true}).addTo(s.map);
  s.selectionLine.on("mouseover",()=>showTerrainWedge(s));
  s.selectionLine.on("mouseout",()=>hideTerrainWedge(s));
  const azIndex=nearestAzimuth(p.az||[],az);
  const sample=nearestDistance(p.distance||[],km);
  const value=p.terrain[azIndex.idx]?.[sample];
  const h=Number.isFinite(value)?Math.round(value)+" m AMSL":"bez dat";
  if(s.profileSummary){
    s.profileSummary.textContent=km.toFixed(2)+" km · "+az.toFixed(1)+
      "° · terén "+h+" · "+latlng.lat.toFixed(5)+"°, "+latlng.lng.toFixed(5)+"°"+
      (km>p.maxRangeKm?" · mimo dosah radaru":"");
  }
  if(s.profilePanel)s.profilePanel.hidden=false;
  drawTerrain(s);
}
function updateProfile(s,data){
  const p=data.profile||null;
  const signature=p?.version||"none";
  if(s.profileSignature===signature)return;
  s.profileSignature=signature;
  if(!p)clearTerrainSelection(s);
  else if(s.selection)selectTerrainPoint(s,L.latLng(s.selection.lat,s.selection.lon));
}
function init(s) {
  const node=s.node;
  const data=s.latest||{};
  const center=data.center||[50.034,15.781];
  s.map=L.map(node,{center,zoom:data.zoom||8,zoomControl:true,preferCanvas:true,
                     zoomSnap:.5,zoomDelta:.5});
  s.map.attributionControl.setPrefix(false);
  s.baseLayers=new Map();s.groups={
    coverage:L.featureGroup().addTo(s.map),
    obstacles:L.featureGroup().addTo(s.map),
    radar:L.featureGroup().addTo(s.map),
    environment:L.featureGroup().addTo(s.map),
    aircraft:L.featureGroup().addTo(s.map),
  };
  s.controls={layers:null,draw:null};
  s.aircraft=new Map();
  s.last={};
  s.map.on("baselayerchange",ev=>{s.activeBaseName=ev.name;});
  s.map.on("click",ev=>{
    const tool=s.latest?.tool;
    if(tool==="Radar"){
      s.trigger("action",{type:"radar",lat:ev.latlng.lat,lon:ev.latlng.lng,
                            id:Date.now()+"-"+Math.random().toString(36).slice(2)});
    }else if(tool==="Prohlížení"&&s.latest?.profile){
      selectTerrainPoint(s,ev.latlng);
    }
  });
  s.profilePanel=s.root.querySelector("#cd-terrain-panel");
  s.profileCanvas=s.root.querySelector("#cd-terrain-canvas");
  s.profileSummary=s.root.querySelector("#cd-terrain-summary");
  const close=s.root.querySelector("#cd-terrain-close");
  if(close)close.addEventListener("click",()=>clearTerrainSelection(s));

  s.map.on(L.Draw.Event.CREATED,ev=>{
    if(s.latest?.tool!=="Polygon"||ev.layerType!=="polygon")return;
    const points=ev.layer.getLatLngs()[0]||[];
    if(points.length<3)return;
    s.trigger("action",{type:"polygon",coordinates:points.map(p=>[p.lat,p.lng]),
                         id:Date.now()+"-"+Math.random().toString(36).slice(2)});
  });
  const size=()=>{
    if(s.map)s.map.invalidateSize({pan:false,animate:false});
    if(s.selection)drawTerrain(s);
  };
  s.resizeObserver=new ResizeObserver(size);
  s.resizeObserver.observe(node);
  if(s.profilePanel)s.resizeObserver.observe(s.profilePanel);
  s.resizeInterval=setTimeout(size,160);
  s.ready=true;
  update(s);
}
function updateOpenAip(s,data) {
  const option=data.openaip||{};
  const sig=JSON.stringify(option);
  if(s.last.openaip===sig)return;
  s.last.openaip=sig;
  if(s.openaipLayer){s.map.removeLayer(s.openaipLayer);s.openaipLayer=null;}
  if(option.enabled&&option.url){
    s.openaipLayer=L.tileLayer(option.url,{maxZoom:18,
      attribution:"Aeronautical data © <a target='_blank' href='https://www.openaip.net/'>OpenAIP</a>",
      opacity:.88});
    s.openaipLayer.addTo(s.map);
  }
  refreshControl(s);
}
function updateCoverage(s,data) {
  const sig=data.coverageVersion||"empty";
  if(s.last.coverage===sig)return;
  s.last.coverage=sig;
  s.groups.coverage.clearLayers();
  for(const record of data.coverage||[]){
    if(!record.geojson?.features?.length)continue;
    const color=record.color||"#247ad3";
    const item=L.geoJSON(record.geojson,{style:()=>({color,weight:1.5,
      fillColor:color,fillOpacity:data.opacity??.4})});
    item.addTo(s.groups.coverage);
  }
}
function updateObstacles(s,data) {
  const sig=data.obstaclesVersion||"empty";
  if(s.last.obstacles===sig)return;
  s.last.obstacles=sig;
  s.groups.obstacles.clearLayers();
  for(const record of data.obstacles||[]){
    const coords=record.coordinates||[];
    if(coords.length<3)continue;
    const poly=L.polygon(coords,{color:"#ee7644",weight:2,
      fillColor:"#ed7b45",fillOpacity:.32});
    poly.bindTooltip(String(record.name||"Překážka")+" · "+String(record.height_m||0)+" m AGL");
    poly.addTo(s.groups.obstacles);
  }
}
function updateRadar(s,data) {
  const sig=JSON.stringify(data.radar||null);
  if(s.last.radar===sig)return;
  s.last.radar=sig;
  s.groups.radar.clearLayers();
  if(!data.radar)return;
  const r=data.radar;
  L.circleMarker([r.lat,r.lon],{radius:7,color:"#ffffff",weight:2,
    fillColor:"#2372d4",fillOpacity:1}).bindTooltip(r.label||"Radar").addTo(s.groups.radar);
}
function updateEnvironment(s,data){
  const sig=data.environmentVersion||"empty";
  if(s.last.environment===sig)return;
  s.last.environment=sig;
  s.groups.environment.clearLayers();
  for(const shape of data.environment||[]){
    if(shape.type==="point"&&Number.isFinite(shape.lat)&&Number.isFinite(shape.lon)){
      L.circleMarker([shape.lat,shape.lon],{radius:4,
        color:shape.color||"#7c97ad",weight:1,fillOpacity:.8})
        .bindTooltip(String(shape.name||"Objekt")).addTo(s.groups.environment);
    }else if(shape.coordinates?.length){
      L.polygon(shape.coordinates,{color:shape.color||"#7c97ad",weight:1,
        fillOpacity:.2}).bindTooltip(String(shape.name||"Objekt")).addTo(s.groups.environment);
    }
  }
}
function updateMode(s,data) {
  if(s.last.tool===data.tool)return;
  s.last.tool=data.tool;
  if(s.controls.draw){s.map.removeControl(s.controls.draw);s.controls.draw=null;}
  if(data.tool==="Polygon") {
    s.controls.draw=new L.Control.Draw({
      position:"topleft",
      draw:{polygon:{allowIntersection:false,showArea:true},
        marker:false,rectangle:false,polyline:false,circle:false,circlemarker:false},
      edit:false,
    });
    s.map.addControl(s.controls.draw);
  }
  s.node.style.cursor=data.tool==="Radar"?"crosshair":"";
}
function refreshAircraft(s,items){
  const seen=new Set();
  for(const ac of items||[]){
    if(typeof ac.lat!=="number"||typeof ac.lon!=="number")continue;
    const id=ac.hex||ac.icao24||String(ac.lat)+":"+String(ac.lon);
    seen.add(id);
    let marker=s.aircraft.get(id);
    if(!marker){
      marker=L.circleMarker([ac.lat,ac.lon],{radius:4,weight:1,
        color:"#1267a7",fillColor:"#1eade0",fillOpacity:.9}).addTo(s.groups.aircraft);
      s.aircraft.set(id,marker);
    }else marker.setLatLng([ac.lat,ac.lon]);
    const alt=typeof ac.alt_geom==="number"?ac.alt_geom:ac.alt_baro;
    marker.bindTooltip(String(ac.flight||id).trim()+" · "+(typeof alt==="number"?Math.round(alt)+" ft":"N/A"));
  }
  for(const [id,marker] of s.aircraft)if(!seen.has(id)){
    s.groups.aircraft.removeLayer(marker);s.aircraft.delete(id);
  }
}
async function fetchAircraft(s){
  if(!s.latest?.live||!s.ready)return;
  const center=s.latest.radar||{lat:50.034,lon:15.781};
  const origin=s.latest.origin||"https://api.adsb.lol";
  const url=origin+"/v2/point/"+center.lat.toFixed(5)+"/"+center.lon.toFixed(5)+"/100";
  try{
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),12000);
    let json;
    try{
      const response=await fetch(url,{signal:controller.signal,cache:"no-store"});
      if(!response.ok)throw new Error("HTTP "+response.status);
      json=await response.json();
    }finally{clearTimeout(timeout);}
    if(!s.latest?.live)return;
    refreshAircraft(s,json.ac||[]);
    status(s,"ADS-B LIVE · "+s.aircraft.size+" letadel · aktualizace 15 s");
  }catch(err){
    status(s,"ADS-B: "+String(err.message||"zdroj nedostupný"));
  }
}
function updateLive(s,data) {
  const old=s.liveSignature, now=JSON.stringify({enabled:!!data.live,radar:data.radar});
  if(old===now)return;
  s.liveSignature=now;
  if(s.timer){clearInterval(s.timer);s.timer=null;}
  if(!data.live){
    refreshAircraft(s,[]);status(s,"");return;
  }
  fetchAircraft(s);
  s.timer=setInterval(()=>fetchAircraft(s),15000);
}
function update(s){
  if(!s.ready)return;
  const data=s.latest||{};
  ensureBaseLayers(s,data);
  updateOpenAip(s,data);
  updateCoverage(s,data);
  updateObstacles(s,data);
  updateRadar(s,data);
  updateProfile(s,data);
  updateEnvironment(s,data);
  updateMode(s,data);
  updateLive(s,data);
  requestAnimationFrame(()=>s.map.invalidateSize({pan:false,animate:false}));
}
export default function(component){
  const root=component.parentElement;
  const node=root.querySelector("#cd-persistent-map");
  if(!node)return;
  let s=INSTANCES.get(node);
  if(!s){
    s={node,root,latest:component.data||{},ready:false,trigger:component.setTriggerValue,
       badge:root.querySelector("#cd-map-status"),timer:null,activeBaseName:"OpenStreetMap"};
    INSTANCES.set(node,s);
    resources().then(()=>{if(node.isConnected)init(s);})
      .catch(e=>status(s,String(e.message||e)));
  }else{
    s.latest=component.data||{};
    s.trigger=component.setTriggerValue;
    update(s);
  }
  return ()=>{
    if(!node.isConnected){
      if(s.timer)clearInterval(s.timer);
      if(s.resizeObserver)s.resizeObserver.disconnect();
      if(s.map)s.map.remove();
      INSTANCES.delete(node);
    }
  };
}
