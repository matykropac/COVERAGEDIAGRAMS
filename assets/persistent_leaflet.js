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
    if(s.latest?.tool!=="Radar")return;
    s.trigger("action",{type:"radar",lat:ev.latlng.lat,lon:ev.latlng.lng,
                          id:Date.now()+"-"+Math.random().toString(36).slice(2)});
  });
  s.map.on(L.Draw.Event.CREATED,ev=>{
    if(s.latest?.tool!=="Polygon"||ev.layerType!=="polygon")return;
    const points=ev.layer.getLatLngs()[0]||[];
    if(points.length<3)return;
    s.trigger("action",{type:"polygon",coordinates:points.map(p=>[p.lat,p.lng]),
                         id:Date.now()+"-"+Math.random().toString(36).slice(2)});
  });
  const size=()=>s.map&&s.map.invalidateSize({pan:false,animate:false});
  s.resizeObserver=new ResizeObserver(size);
  s.resizeObserver.observe(node);
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
    s={node,latest:component.data||{},ready:false,trigger:component.setTriggerValue,
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
