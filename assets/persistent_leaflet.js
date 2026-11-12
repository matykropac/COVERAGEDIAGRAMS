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
    const cls=spec.name.includes("Satelitní")?"cd-satellite-tile":"cd-basemap-tile";
    const layer=L.tileLayer(spec.url,{attribution:spec.attribution||"",
      maxZoom:spec.max_zoom||19,crossOrigin:false,className:cls});
    next.set(spec.name,layer);
  }
  const chosen=next.get(oldName)||next.get("OpenStreetMap")||next.values().next().value;
  for(const layer of s.baseLayers.values())s.map.removeLayer(layer);
  s.baseLayers=next;
  s.activeBaseName=[...next].find(([_,layer])=>layer===chosen)?.[0]||oldName;
  if(chosen)chosen.addTo(s.map);
  refreshControl(s);
}
function updateDayNight(s,data){
  const theme=data.theme==="NIGHT"?"NIGHT":"DAY";
  if(s.currentTheme===theme)return;
  s.currentTheme=theme;
  s.node.classList.toggle("cd-night",theme==="NIGHT");
  // The DOM/CSS changes only the tile appearance. No requests or map reset.
}

function refreshControl(s) {
  if(s.controls.layers){s.map.removeControl(s.controls.layers);s.controls.layers=null;}
  const bases={};
  for(const [name,layer] of s.baseLayers) bases[name]=layer;
  const overlay={
    "Radarové krytí":s.groups.coverage,
    "RWY / Airport geometry":s.groups.airport,
    "RANGE · NM":s.groups.range,
    "Překážky":s.groups.obstacles,
    "Radar":s.groups.radar,
    "Další geodata":s.groups.environment,
    "PAR · sektor ±15°":s.groups.parSector,
  };
  // OpenAIP is permanently enabled when configured, not a user-toggle layer.
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
  if(s.root)s.root.classList.remove("cd-profile-active");
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
  if(s.root)s.root.classList.add("cd-profile-active");
  requestAnimationFrame(()=>s.map.invalidateSize({pan:false,animate:false}));
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
                     zoomSnap:.5,zoomDelta:.5,zoomAnimation:false,
                     fadeAnimation:false,markerZoomAnimation:false});
  s.map.attributionControl.setPrefix(false);
  s.baseLayers=new Map();s.groups={
    coverage:L.featureGroup().addTo(s.map),
    airport:L.featureGroup().addTo(s.map),
    airspaces:L.featureGroup().addTo(s.map),
    range:L.featureGroup().addTo(s.map),
    obstacles:L.featureGroup().addTo(s.map),
    radar:L.featureGroup().addTo(s.map),
    environment:L.featureGroup().addTo(s.map),
    aircraft:L.featureGroup().addTo(s.map),
    parSector:L.featureGroup().addTo(s.map),
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
    }else if(tool==="PAR_AIM"){
      const radar=s.latest?.radar;
      if(!radar||!Number.isFinite(Number(radar.lat))||!Number.isFinite(Number(radar.lon)))return;
      const raw=geodesic([Number(radar.lat),Number(radar.lon)],ev.latlng).az;
      const bearing=parSnapBearing(s,raw).bearing;
      s.trigger("action",{type:"par_aim",bearing,
                            id:Date.now()+"-"+Math.random().toString(36).slice(2)});
    }else if(tool==="Validate"){
      s.trigger("action",{type:"validate_los",lat:ev.latlng.lat,lon:ev.latlng.lng,
                            id:Date.now()+"-"+Math.random().toString(36).slice(2)});
    }else if(tool==="Prohlížení"&&s.latest?.profile){
      selectTerrainPoint(s,ev.latlng);
    }
  });
  // Pointer preview stays entirely client-side; Streamlit gets just the final click.
  s.map.on("mousemove",event=>{
    if(s.latest?.tool!=="PAR_AIM"||!s.parGuide||s.parPointerInsideControl)return;
    const cfg=s.latest?.parSector;
    if(!cfg?.enabled)return;
    const raw=geodesic([Number(cfg.lat),Number(cfg.lon)],event.latlng).az;
    s.parPendingBearing=raw;
    if(s.parAimFrame)return;
    s.parAimFrame=requestAnimationFrame(()=>{
      s.parAimFrame=null;
      if(s.latest?.tool!=="PAR_AIM"||!s.parGuide)return;
      const candidate=parSnapBearing(s,s.parPendingBearing);
      s.parPreviewBearing=candidate.bearing;
      parRedraw(s,candidate.bearing,candidate.snapped);
    });
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
  // The floating controls do not resize the map. Only invalidate Leaflet
  // when its actual viewport dimensions change; coalesce redundant callbacks.
  let lastWidth=0,lastHeight=0;
  const size=()=>{
    if(!s.map||!node.isConnected)return;
    const {width,height}=node.getBoundingClientRect();
    if(width<=0||height<=0||Math.abs(width-lastWidth)<.5&&Math.abs(height-lastHeight)<.5)return;
    lastWidth=width;lastHeight=height;
    if(s.sizeFrame)cancelAnimationFrame(s.sizeFrame);
    s.sizeFrame=requestAnimationFrame(()=>{
      if(!s.map||!node.isConnected)return;
      s.map.invalidateSize({pan:false,animate:false});
      if(s.selection)drawTerrain(s);
    });
  };
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
  const oldWarning=s.root.querySelector("#cd-openaip-warning");
  if(oldWarning)oldWarning.remove();
  if(s.openaipLayer){s.map.removeLayer(s.openaipLayer);s.openaipLayer=null;}
  if(option.enabled&&option.url){
    s.openaipLayer=L.tileLayer(option.url,{maxZoom:18,className:"cd-aip-tile",
      updateWhenIdle:true,updateWhenZooming:false,keepBuffer:2,
      attribution:"Aeronautical data © <a target='_blank' href='https://www.openaip.net/'>OpenAIP</a>",
      opacity:.88});
    // OpenAIP failures were previously silent: a checked overlay could be blank.
    // Keep diagnostics separate from ADS-B status and never expose the API key.
    let errors=0,loaded=0;
    const warn=(message)=>{
      let banner=s.root.querySelector("#cd-openaip-warning");
      if(!banner){
        banner=document.createElement("div");
        banner.id="cd-openaip-warning";
        banner.setAttribute("role","alert");
        banner.style.cssText="position:absolute;top:80px;left:50%;transform:translateX(-50%);z-index:1000;max-width:min(620px,85%);padding:9px 14px;border-radius:6px;background:#fff4e6;border:1px solid #e3a24d;color:#673c0e;font:13px system-ui;box-shadow:0 2px 10px #0002;";
        s.node.appendChild(banner);
      }
      banner.textContent=message;
    };
    s.openaipLayer.on("tileerror",()=>{
      errors++;
      if(errors>=2 && loaded===0)warn("OpenAIP: dlaždice se nepodařilo načíst (síť / 401 / 403 / 429). Zkontroluj konfiguraci API klíče a dostupnost služby.");
    });
    s.openaipLayer.on("tileload",()=>{
      loaded++;
      const banner=s.root.querySelector("#cd-openaip-warning");
      if(banner)banner.remove();
    });
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
    const previous=!!record.previous;
    const item=L.geoJSON(record.geojson,{style:()=>({color,
      weight:previous?2.3:1.5,dashArray:previous?"7 5":null,
      fillColor:color,fillOpacity:previous?0:(data.opacity??.4)})});
    item.addTo(s.groups.coverage);
  }
}
function updateAirspaces(s,data){
  const sig=data.airspacesVersion||"empty";
  if(s.last.airspaces===sig)return;
  s.last.airspaces=sig;
  s.groups.airspaces.clearLayers();
  const zones=(data.airspaces||[]).slice(0,200);
  for(const z of zones){
    if(!z.geometry||!["CTR","TMA"].includes(z.kind))continue;
    const ctr=z.kind==="CTR";
    const color=ctr?"#2075dc":"#7356c7";
    const line=L.geoJSON(z.geometry,{
      style:()=>({color,weight:ctr?2.1:2.4,
        dashArray:ctr?null:"8 5",fillColor:color,fillOpacity:ctr?.065:.045}),
      bubblingMouseEvents:false
    });
    const details=[String(z.name||z.kind),z.kind+" · CLASS "+String(z.class||"?"),
      "LOWER: "+String(z.lower?.text||"N/A"),
      "UPPER: "+String(z.upper?.text||"N/A"),
      "SOURCE: "+String(z.source||"OpenAIP")+" · unofficial"].join("\n");
    line.bindTooltip(details,{sticky:true});
    line.bindPopup(
      "<strong>"+escapeAirspaceText(z.name||z.kind)+"</strong>"+
      "<p>TYPE: "+escapeAirspaceText(z.kind)+" · CLASS: "+escapeAirspaceText(z.class||"?")+"</p>"+
      "<p>LOWER: "+escapeAirspaceText(z.lower?.text||"N/A")+
      "<br>UPPER: "+escapeAirspaceText(z.upper?.text||"N/A")+"</p>"+
      "<small>"+escapeAirspaceText(z.source||"OpenAIP")+" · reference only, verify with official AIP</small>"
    );
    line.addTo(s.groups.airspaces);
  }
}
function escapeAirspaceText(v){
  return String(v).replace(/[&<>"']/g,c=>({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function updateAirport(s,data){
  const geometries=data.airportGeometry||[];
  const sig=JSON.stringify([geometries,data.airportCode||""]);
  if(s.last.airport===sig)return;
  s.last.airport=sig;
  s.groups.airport.clearLayers();
  for(const g of geometries){
    if(!g.centerline?.length||!g.extended?.length)continue;
    const code=String(data.airportCode||"");
    const label=code+" · RWY "+String(g.label||"");
    L.polyline(g.extended,{color:"#b78b1c",weight:1.6,dashArray:"6 5",
      interactive:false}).addTo(s.groups.airport);
    L.polyline(g.centerline,{color:"#2c5266",weight:5,opacity:.9})
      .bindTooltip(label+" · TRUE "+String(g.true_bearing)+"°")
      .addTo(s.groups.airport);
    for(let i=0;i<(g.thresholds||[]).length;i++){
      const point=g.thresholds[i];
      L.circleMarker(point,{radius:4,color:"#ffffff",weight:1.5,
        fillColor:"#df6f37",fillOpacity:1})
        .bindTooltip(label+" · THR "+String(i===0?"A":"B"))
        .addTo(s.groups.airport);
    }
    L.circleMarker(g.midpoint,{radius:3,color:"#ffffff",weight:1.2,
      fillColor:"#2676be",fillOpacity:1})
      .bindTooltip(label+" · MIDPOINT").addTo(s.groups.airport);
  }
}
function highlightObstacle(s,layer){
  if(s.highlightedObstacle && s.highlightedObstacle!==layer){
    const old=s.highlightedObstacle;
    if(old.__cdOriginalStyle)old.setStyle(old.__cdOriginalStyle);
  }
  if(!layer.__cdOriginalStyle){
    layer.__cdOriginalStyle={
      color:layer.options.color,weight:layer.options.weight,
      fillOpacity:layer.options.fillOpacity
    };
  }
  layer.setStyle({color:"#226be6",weight:4,fillOpacity:.46});
  if(layer.bringToFront)layer.bringToFront();
  s.highlightedObstacle=layer;
}
function requestObstacleEdit(s,kind,id){
  if(id===null||id===undefined||id==="")return;
  s.trigger("action",{type:"edit_obstacle",kind,obstacle_id:String(id),
    id:Date.now()+"-"+Math.random().toString(36).slice(2)});
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
      fillColor:"#ed7b45",fillOpacity:.32,bubblingMouseEvents:false});
    poly.bindTooltip(String(record.name||"Překážka")+" · "+String(record.height_m||0)+" m AGL");
    poly.on("click",ev=>{
      L.DomEvent.stopPropagation(ev);
      highlightObstacle(s,poly);
      requestObstacleEdit(s,"manual",record.id);
    });
    poly.addTo(s.groups.obstacles);
  }
}
function updateRadar(s,data) {
  const radar=data.radar||null;
  const sig=JSON.stringify(radar);
  if(s.last.radar===sig)return;
  s.last.radar=sig;
  s.groups.radar.clearLayers();
  if(!radar)return;
  const lat=Number(radar.lat),lon=Number(radar.lon);
  if(!Number.isFinite(lat)||!Number.isFinite(lon)||Math.abs(lat)>90||Math.abs(lon)>180){
    status(s,"Radar: chybné souřadnice stanoviště.");
    return;
  }
  L.circleMarker([lat,lon],{radius:7,color:"#ffffff",weight:2,
    fillColor:"#2372d4",fillOpacity:1}).bindTooltip(radar.label||"Radar").addTo(s.groups.radar);
  // On loading a project or changing its site, reposition the actual map,
  // not just its radar marker. Never recenter for an ordinary UI rerun.
  const site=[lat,lon];
  if(!s.lastRadarSite||Math.abs(s.lastRadarSite[0]-lat)>1e-7||
                        Math.abs(s.lastRadarSite[1]-lon)>1e-7){
    s.lastRadarSite=site;
    const at=s.map.getCenter();
    if(Math.abs(at.lat-lat)>1e-6||Math.abs(at.lng-lon)>1e-6)
      s.map.setView(site,s.map.getZoom(),{animate:false});
  }
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
      const p=L.polygon(shape.coordinates,{color:shape.color||"#7c97ad",weight:1.2,
        fillOpacity:.22,bubblingMouseEvents:false})
        .bindTooltip(String(shape.name||"Objekt"));
      if(shape.id){
        p.on("click",ev=>{
          L.DomEvent.stopPropagation(ev);
          highlightObstacle(s,p);
          requestObstacleEdit(s,"catalog",shape.id);
        });
      }
      p.addTo(s.groups.environment);
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
  s.node.style.cursor=(data.tool==="Radar"||data.tool==="Validate"||data.tool==="PAR_AIM")?"crosshair":"";
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

function parDestination(lat,lon,azDeg,distanceKm){
  // Geodesic direct solution on a spherical Earth; used for visual sector
  // guide only, never to drive the solver or its DEM sampling.
  const r=6371.0088,rad=Math.PI/180;
  const phi1=lat*rad,lambda1=lon*rad,theta=azDeg*rad;
  const delta=distanceKm/r;
  const phi2=Math.asin(Math.sin(phi1)*Math.cos(delta)+
                       Math.cos(phi1)*Math.sin(delta)*Math.cos(theta));
  const lambda2=lambda1+Math.atan2(Math.sin(theta)*Math.sin(delta)*Math.cos(phi1),
                     Math.cos(delta)-Math.sin(phi1)*Math.sin(phi2));
  return [phi2/rad,((lambda2/rad+540)%360)-180];
}
function parRunwayAzimuth(cfg){
  const rw=cfg?.referenceRunway;
  const raw=Number(rw?.heading_deg_true);
  return rw && Number.isFinite(raw)
    ? ((raw+(Number(cfg.referenceEnd)===1?180:0))%360+360)%360
    : null;
}
function parAngleDifference(a,b){
  return Math.abs(((a-b+540)%360)-180);
}
function parSnapBearing(s,raw){
  const bearing=((raw%360)+360)%360;
  const cfg=s.latest?.parSector||{};
  if(!s.parMagnetOn)return {bearing,snapped:false};
  const runways=(Array.isArray(cfg.referenceRunways)&&cfg.referenceRunways.length)
    ? cfg.referenceRunways : (cfg.referenceRunway?[cfg.referenceRunway]:[]);
  const references=[];
  for(const runway of runways){
    const az=Number(runway.heading_deg_true);
    if(!Number.isFinite(az))continue;
    for(const offset of [0,90,180,270])references.push((az+offset)%360);
  }
  if(!references.length)return {bearing,snapped:false};
  let best=bearing,error=Infinity;
  for(const ref of references){
    const diff=parAngleDifference(bearing,ref);
    if(diff<error){error=diff;best=ref;}
  }
  return error<=8?{bearing:best,snapped:true}:{bearing,snapped:false};
}
function parRay(lat,lon,az,distance){
  return [lat===null?null:[lat,lon],parDestination(lat,lon,az,distance)];
}
function parRedraw(s,bearing,snapped=false){
  const guide=s.parGuide;if(!guide)return;
  const {lat,lon,distance}=guide;
  const site=[lat,lon];
  for(const sector of guide.sectors){
    const center=bearing+sector.reverse;
    const arc=[];
    for(let step=-15;step<=15;step+=1)
      arc.push(parDestination(lat,lon,center+step,distance));
    sector.area.setLatLngs([site,...arc,site]);
    sector.left.setLatLngs([site,arc[0]]);
    sector.right.setLatLngs([site,arc[arc.length-1]]);
    sector.axis.setLatLngs([site,parDestination(lat,lon,center,distance)]);
  }
  const inside=parDestination(lat,lon,bearing,distance*.50);
  guide.marker.setLatLng(inside);
  if(guide.heading)guide.heading.textContent=bearing.toFixed(2)+"° TRUE";
  if(guide.magnetStatus)
    guide.magnetStatus.textContent=snapped?"MAGNET · PŘICHYCENO":"MAGNET · "+(s.parMagnetOn?"ZAPNUT":"VYPNUT");
  if(guide.label)guide.label.textContent="PAR · "+bearing.toFixed(2)+"° TRUE";
  if(guide.input && document.activeElement!==guide.input)guide.input.value=bearing.toFixed(2);
}
function updateParSector(s,data){
  const cfg=data.parSector||{};
  const enabled=cfg.enabled===true;
  const aiming=data.tool==="PAR_AIM";
  const sig=JSON.stringify([enabled,cfg.lat,cfg.lon,cfg.bearing,cfg.rangeKm,
      cfg.referenceRunway?.key,cfg.referenceRunway?.heading_deg_true,
      (cfg.referenceRunways||[]).map(r=>[r.key,r.label,r.heading_deg_true]),cfg.referenceEnd,aiming]);
  if(s.last.parSector===sig)return;
  s.last.parSector=sig;
  if(s.parAimFrame){cancelAnimationFrame(s.parAimFrame);s.parAimFrame=null;}
  s.parGuide=null;
  s.parPointerInsideControl=false;
  s.groups.parSector.clearLayers();
  if(!enabled)return;
  const lat=Number(cfg.lat),lon=Number(cfg.lon),az=Number(cfg.bearing);
  const distance=Number(cfg.rangeKm);
  if(!Number.isFinite(lat)||!Number.isFinite(lon)||!Number.isFinite(az)||
     !Number.isFinite(distance)||distance<=0)return;
  const site=[lat,lon];
  const runways=(Array.isArray(cfg.referenceRunways)&&cfg.referenceRunways.length)
    ? cfg.referenceRunways : (cfg.referenceRunway?[cfg.referenceRunway]:[]);
  // Each RWY is an independently named pair of axes, even for parallel
  // runways. Their source is indicative until certified threshold data exist.
  for(let index=0;index<runways.length;index++){
    const runway=runways[index];
    const az=Number(runway.heading_deg_true);
    if(!Number.isFinite(az))continue;
    const label=String(runway.label||"RWY "+(index+1));
    for(const [offset,color,name] of [
      [0,"#f08ae8","ROVNOBĚŽKA"],[90,"#b3f0a4","KOLMICE"]
    ]){
      const angle=(az+offset)%360;
      const coords=[
        parDestination(lat,lon,angle+180,distance),site,
        parDestination(lat,lon,angle,distance)
      ];
      L.polyline(coords,{color,weight:2,dashArray:"10 7",
        opacity:.76,interactive:false})
       .bindTooltip(name+" RWY "+label+" · "+angle.toFixed(2)+"° TRUE")
       .addTo(s.groups.parSector);
    }
  }
  const sectors=[];
  for(const reverse of [0,180]){
    const area=L.polygon([],{color:"#2bbfe8",weight:1,opacity:.8,
      fillColor:"#23b0e9",fillOpacity:.12,interactive:false})
      .addTo(s.groups.parSector);
    const left=L.polyline([],{color:"#4fd4ff",weight:2,
      dashArray:"6 5",interactive:false}).addTo(s.groups.parSector);
    const right=L.polyline([],{color:"#4fd4ff",weight:2,
      dashArray:"6 5",interactive:false}).addTo(s.groups.parSector);
    const axis=L.polyline([],{color:"#f8cf67",weight:3,
      interactive:false}).addTo(s.groups.parSector);
    sectors.push({reverse,area,left,right,axis});
  }
  const labelHTML=aiming
   ? '<div class="cd-par-inside-editor"><div class="cd-par-inside-title">⌖ OSA PAR · OBOUSTRANNÝ SEKTOR</div>'+
     '<div class="cd-par-heading"></div>'+
     '<div class="cd-par-inside-row"><input class="cd-par-angle" type="number" min="0" max="359.99" step="0.01" value="'+
      az.toFixed(2)+'" aria-label="TRUE azimut PAR"><button type="button" class="cd-par-confirm">✓</button></div>'+
     '<label class="cd-par-magnet"><input class="cd-par-magnet-toggle" type="checkbox" checked> 🧲 MAGNET · 8°</label>'+
     '<small class="cd-par-snap-status">MAGNET · ZAPNUT</small></div>'
   : '<div class="cd-par-inside-label"><span class="cd-par-static-label">PAR · '+az.toFixed(2)+'° TRUE</span> <small>±15° × 2</small></div>';
  const marker=L.marker(site,{interactive:aiming,keyboard:false,
    icon:L.divIcon({html:labelHTML,className:"cd-par-inside-icon",iconSize:[0,0]})
  }).addTo(s.groups.parSector);
  const root=marker.getElement();
  const guide={lat,lon,distance,sectors,marker,
    input:root?.querySelector(".cd-par-angle"),
    heading:root?.querySelector(".cd-par-heading"),
    magnetStatus:root?.querySelector(".cd-par-snap-status"),
    label:root?.querySelector(".cd-par-static-label")};
  s.parGuide=guide;
  if(aiming){
    const editor=root?.querySelector(".cd-par-inside-editor");
    const confirm=root?.querySelector(".cd-par-confirm");
    const magnet=root?.querySelector(".cd-par-magnet-toggle");
    if(editor&&guide.input&&confirm&&magnet){
      if(s.parMagnetOn===undefined)s.parMagnetOn=true;
      magnet.checked=s.parMagnetOn;
      L.DomEvent.disableClickPropagation(editor);
      L.DomEvent.disableScrollPropagation(editor);
      editor.addEventListener("mouseenter",()=>{s.parPointerInsideControl=true;});
      editor.addEventListener("mouseleave",()=>{s.parPointerInsideControl=false;});
      magnet.addEventListener("change",()=>{
        s.parMagnetOn=magnet.checked;
        const raw=s.parPendingBearing??az;
        const candidate=parSnapBearing(s,raw);
        s.parPreviewBearing=candidate.bearing;
        parRedraw(s,candidate.bearing,candidate.snapped);
      });
      const submit=()=>{
        const number=Number(guide.input.value);
        if(!guide.input.value.trim()||!Number.isFinite(number)||number<0||number>=360){
          guide.input.setCustomValidity("Zadej azimut 0 až 359,99°.");
          guide.input.reportValidity();return;
        }
        guide.input.setCustomValidity("");
        s.trigger("action",{type:"par_aim",bearing:number,
          id:Date.now()+"-"+Math.random().toString(36).slice(2)});
      };
      confirm.addEventListener("click",submit);
      guide.input.addEventListener("keydown",event=>{
        event.stopPropagation();
        if(event.key==="Enter"){event.preventDefault();submit();}
      });
      // Numeric editing also updates the geometry live, but leaves the
      // value exact; magnetic snapping is only for cursor-guided targeting.
      guide.input.addEventListener("input",()=>{
        const n=Number(guide.input.value);
        if(guide.input.value.trim()&&Number.isFinite(n)&&n>=0&&n<360){
          s.parPreviewBearing=n;
          parRedraw(s,n,false);
        }
      });
    }
  }
  parRedraw(s,az,false);
}
function updateRange(s,data){
  const nm=Number(data.rangeNm||20);
  const enabled=!!data.rangeEnabled;
  const points=Array.isArray(data.rangeCircle)?data.rangeCircle:[];
  const radar=data.radar||{};
  const signature=JSON.stringify([enabled,nm,radar.lat,radar.lon]);
  if(s.last.range===signature)return;
  s.last.range=signature;
  s.groups.range.clearLayers();
  if(!enabled||points.length<3)return;
  const circle=L.polygon(points,{
    color:"#14b8ff",weight:2,opacity:0.95,fill:false,
    dashArray:"7 5",interactive:true
  });
  circle.bindTooltip("RANGE · "+nm+" NM ("+(nm*1.852).toFixed(2)+" km)",{sticky:true});
  circle.addTo(s.groups.range);
}
function update(s){
  if(!s.ready)return;
  const data=s.latest||{};
  ensureBaseLayers(s,data);
  updateDayNight(s,data);
  updateOpenAip(s,data);
  updateCoverage(s,data);
  updateAirport(s,data);
  updateAirspaces(s,data);
  updateRange(s,data);
  updateObstacles(s,data);
  updateRadar(s,data);
  updateParSector(s,data);
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
      if(s.sizeFrame)cancelAnimationFrame(s.sizeFrame);
      if(s.map)s.map.remove();
      INSTANCES.delete(node);
    }
  };
}
