"""COVERAGEDIAGRAMS VIEWER – independent map and DEM visualization workspace."""
from __future__ import annotations

import io
import json
import zipfile
from collections import defaultdict
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

import folium
import numpy as np
import pandas as pd
import streamlit as st
import radar_core as core
import html
import re
from folium.plugins import Fullscreen, MeasureControl
from streamlit_folium import st_folium

K = "{http://www.opengis.net/kml/2.2}"
BASEMAPS = {
    "NIGHT · Dark Matter": ("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", "© OpenStreetMap © CARTO"),
    "OpenStreetMap": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "© OpenStreetMap contributors"),
    "Esri World Imagery": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "Tiles © Esri"),
    "Esri World Topographic": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}", "Tiles © Esri"),
    "OpenTopoMap": ("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", "© OpenTopoMap, OpenStreetMap"),
}
PALETTE = ["#2563eb", "#14b8a6", "#e879f9", "#ef8a27", "#d94658", "#8b5cf6", "#84cc16"]


def _coords(text):
    output = []
    for item in (text or "").split():
        try:
            parts = item.split(",")
            output.append([float(parts[0]), float(parts[1]), float(parts[2]) if len(parts)>2 else 0.0])
        except (ValueError, IndexError):
            continue
    return output


def _geometry(node):
    if node.tag == K+"Point":
        points = _coords(node.findtext(K+"coordinates"))
        return {"type": "Point", "coordinates": points[0]} if points else None
    if node.tag == K+"LineString":
        points = _coords(node.findtext(K+"coordinates"))
        return {"type":"LineString", "coordinates":points} if len(points)>=2 else None
    if node.tag == K+"Polygon":
        rings = []
        outer = node.find(K+"outerBoundaryIs/"+K+"LinearRing/"+K+"coordinates")
        if outer is not None:
            rings.append(_coords(outer.text))
        for inner in node.findall(K+"innerBoundaryIs/"+K+"LinearRing/"+K+"coordinates"):
            rings.append(_coords(inner.text))
        return {"type":"Polygon", "coordinates":rings} if rings and len(rings[0])>=3 else None
    if node.tag == K+"MultiGeometry":
        gs = [_geometry(c) for c in node]
        gs = [g for g in gs if g]
        return {"type":"GeometryCollection","geometries":gs} if gs else None
    return None


def _parse_kml(data, filename):
    root = ET.fromstring(data)
    groups = defaultdict(list)
    def walk(node, current):
        for child in node:
            if child.tag in (K+"Folder",K+"Document"):
                name = child.findtext(K+"name") or current
                walk(child, name if child.tag == K+"Folder" else current)
            elif child.tag == K+"Placemark":
                geom = next((_geometry(c) for c in child if c.tag in
                             (K+"Point",K+"LineString",K+"Polygon",K+"MultiGeometry")),None)
                if geom:
                    groups[current].append({"type":"Feature","properties":{
                        "name":child.findtext(K+"name") or "Unnamed",
                        "description":child.findtext(K+"description") or "",
                        "source":filename},"geometry":geom})
    walk(root, "Imported")
    return dict(groups)


def _load_layers(upload):
    data = upload.getvalue()
    name = upload.name
    if name.lower().endswith(".kmz"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = [i for i in z.infolist() if i.filename.lower().endswith(".kml")
                       and not i.is_dir() and i.file_size <= 30_000_000]
            if not members:
                raise ValueError("KMZ neobsahuje čitelný KML dokument.")
            data = z.read(next((m for m in members if PurePosixPath(m.filename).name.lower()=="doc.kml"),members[0]))
    if name.lower().endswith((".kml",".kmz")):
        return _parse_kml(data,name)
    payload = json.loads(data.decode("utf-8-sig"))
    if payload.get("type") == "FeatureCollection":
        return {"GeoJSON": payload.get("features",[])}
    if payload.get("type") == "Feature":
        return {"GeoJSON":[payload]}
    raise ValueError("Nepodporovaný GeoJSON formát.")


def _iter_coords(geometry):
    if not geometry:
        return
    t = geometry.get("type")
    if t == "GeometryCollection":
        for part in geometry.get("geometries",[]):
            yield from _iter_coords(part)
    elif t == "Point":
        yield geometry["coordinates"]
    elif t in ("LineString","MultiPoint"):
        yield from geometry["coordinates"]
    elif t in ("Polygon","MultiLineString"):
        for ring in geometry["coordinates"]:
            yield from ring
    elif t == "MultiPolygon":
        for poly in geometry["coordinates"]:
            for ring in poly:
                yield from ring


def _dem_from_bytes(data, max_size=180):
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.warp import transform as reproject_points
    with MemoryFile(data) as memory, memory.open() as src:
        if src.crs is None:
            raise ValueError("Výškový rastr nemá definovaný souřadnicový systém.")
        h,w = src.height, src.width
        stride = max(1, int(np.ceil(max(h,w)/max_size)))
        from rasterio.enums import Resampling
        out_h=max(2,int(np.ceil(h/stride)))
        out_w=max(2,int(np.ceil(w/stride)))
        band=src.read(1,out_shape=(out_h,out_w),masked=True,resampling=Resampling.average)
        z=np.ma.filled(band.astype("float64"),np.nan)
        from rasterio.transform import from_bounds
        tr=from_bounds(*src.bounds,out_w,out_h)
        cols=np.arange(out_w,dtype=float)+0.5
        rows=np.arange(out_h,dtype=float)+0.5
        xx,yy=np.meshgrid(cols,rows)
        east=tr.c+tr.a*xx+tr.b*yy
        north=tr.f+tr.d*xx+tr.e*yy
        latlon=src.crs.to_epsg()==4326
        if latlon:
            lon,lat=east,north
        else:
            lon_flat,lat_flat=reproject_points(src.crs,"EPSG:4326",east.ravel().tolist(),north.ravel().tolist())
            lon=np.asarray(lon_flat).reshape(east.shape)
            lat=np.asarray(lat_flat).reshape(east.shape)
        return lon,lat,z



def _snapshot():
    token=st.query_params.get("snapshot")
    if not token:
        return None,None
    try:
        from viewer_bridge import acquire
        @st.cache_resource(show_spinner=False,max_entries=8)
        def cached_snapshot(token):
            return acquire(token)
        return cached_snapshot(str(token))
    except Exception as exc:
        st.warning("Projekt z EDITORU se nepodařilo načíst: "+str(exc))
        return None,None


def _bbox(lat,lon,radius_km):
    from pyproj import Geod
    az=np.arange(0,360,5,dtype=float)
    lons,lats,_=Geod(ellps="WGS84").fwd(
        np.full(len(az),float(lon)),np.full(len(az),float(lat)),
        az,np.full(len(az),float(radius_km)*1000))
    return dict(south=float(min(lats)),north=float(max(lats)),
                west=float(min(lons)),east=float(max(lons)))


@st.dialog("STÁHNOUT DIGITÁLNÍ MODEL TERÉNU",width="large")
def download_dem_dialog(center):
    """User-controlled OpenTopography request, with the existing core cache."""
    st.caption("OpenTopography Global DEM · autentický výškový model terénu. "
               "Po stažení se 3D scéna aktualizuje automaticky.")
    a,b=st.columns(2)
    with a:
        lat=st.number_input("Střed · LAT",min_value=-80.0,max_value=80.0,
                            value=float(np.clip(center[0],-80,80)),format="%.6f",key="viewer_dl_lat")
    with b:
        lon=st.number_input("Střed · LON",min_value=-180.0,max_value=180.0,
                            value=float(np.clip(center[1],-180,180)),format="%.6f",key="viewer_dl_lon")
    dataset=st.selectbox("Výškový model",core.DATASETS,index=0,key="viewer_dl_dataset",
                         help="COP30 má přibližně 30m rozlišení; COP90 přibližně 90m.")
    radius=st.slider("Poloměr stažení [km]",2,250,35,1,key="viewer_dl_radius")
    st.caption("Oblast stahování je obdélník kolem středu. Limit velikosti kontroluje OpenTopography klient.")
    import os
    key=os.environ.get("OPENTOPOGRAPHY_API_KEY","").strip()
    if not key:
        try:
            key=str(st.secrets.get("OPENTOPOGRAPHY_API_KEY","")).strip()
        except (FileNotFoundError,KeyError,OSError):
            pass
    if not key:
        key=st.text_input("OpenTopography API key",type="password",key="viewer_dl_api",
                          help="Klíč se neukládá do projektu.")
    if st.button("STÁHNOUT TERÉN DO VIEWERU",type="primary",
                 use_container_width=True,key="viewer_dl_start"):
        try:
            if not key:
                raise ValueError("Chybí OpenTopography API key.")
            with st.status("Načítám DEM z OpenTopography",expanded=True) as status:
                event=st.empty()
                def progress(msg,*_):
                    event.caption(str(msg).replace(key,"[API KEY]"))
                path=core.download(None,key,dataset,progress,
                                   bbox=_bbox(lat,lon,radius))
                # Validate before accepting a downloaded file.
                _dem_from_bytes(path.read_bytes(),max_size=12)
                st.session_state["viewer_dem_path"]=str(path)
                st.session_state["viewer_dem_source"]=f"OpenTopography · {dataset} · {radius} km"
                status.update(label="DEM připraven · "+dataset,state="complete")
            st.rerun()
        except Exception as exc:
            st.error("Stažení DEM selhalo: "+str(exc).replace(key,"[API KEY]") if key else str(exc))


def _polar_dem(result,max_size=160):
    """Convert the actual editor radar-sampled DEM from polar to WGS84 mesh."""
    from pyproj import Geod
    az=np.asarray(result["az"],dtype=float)
    dist=np.asarray(result["distance"],dtype=float)
    ai=np.unique(np.linspace(0,len(az)-1,min(len(az),max_size)).astype(int))
    di=np.unique(np.linspace(0,len(dist)-1,min(len(dist),max_size)).astype(int))
    angles=np.broadcast_to(az[ai,None],(len(ai),len(di)))
    ranges=np.broadcast_to(dist[None,di],angles.shape)
    cfg=result["config"]
    lon,lat,_=Geod(ellps="WGS84").fwd(
        np.full(angles.shape,cfg.lon),np.full(angles.shape,cfg.lat),
        angles,ranges)
    z=np.asarray(result["terrain"],dtype=float)[np.ix_(ai,di)]
    return lon,lat,z


def _editor_layers(result,meta):
    from web_support import coverage_geojson
    selected=meta.get("levels",[]) if isinstance(meta,dict) else []
    available=set(core.flight_levels_for(result["config"].radar_mode))
    selected=[ft for ft in selected if ft in available]
    if not selected:
        selected=list(core.flight_levels_for(result["config"].radar_mode))[:3]
    if st.session_state.get("viewer_import_all_fl"):
        selected=list(core.flight_levels_for(result["config"].radar_mode))
    collections={}
    for ft in selected:
        try:
            collections["RADAR / "+core.level_label(ft)]=coverage_geojson(result,ft).get("features",[])
        except Exception as exc:
            st.warning(f"Vrstva {ft} ft není dostupná: {exc}")
    return collections


def _three_dimensional(layers, visible, editor_result=None, center=(50.,15.), styles=None, title='RADAR COVERAGE'):
    import plotly.graph_objects as go
    if st.button("☁ STÁHNOUT TERÉN · OPENTOPOGRAPHY",type="primary",
                 key="viewer_download_3d"):
        download_dem_dialog(center)
    stored=st.session_state.get("viewer_dem_path")
    try:
        if stored:
            from pathlib import Path
            path=Path(stored)
            if not path.is_file():
                raise FileNotFoundError("Stažený model již není dostupný v cache.")
            lon,lat,z=_dem_from_bytes(path.read_bytes())
            st.caption(st.session_state.get("viewer_dem_source","Stažený výškový model"))
        elif editor_result is not None:
            lon,lat,z=_polar_dem(editor_result)
            st.caption("DEM automaticky převzatý z EDITORU · radiálně vzorkovaný terén")
        else:
            st.info("Pro 3D terén vyber STÁHNOUT TERÉN a nastav oblast a dataset. "
                    "Žádný soubor nemusíš ručně nahrávat.")
            return
    except Exception as e:
        st.error(f"DEM nelze načíst: {e}")
        return
    if not np.any(np.isfinite(z)):
        st.error("DEM neobsahuje platné výšky.")
        return
    scale=st.slider("Vertikální převýšení (vizuální)",1.0,8.0,2.0,0.5,key="viewer_exaggeration")
    palette=st.selectbox("Hypsometrie",["Terrain","Viridis","Earth","Turbo","Greys"],key="viewer_hypsometry")
    # Plotly supports Viridis/Earth/Turbo/Greys but not the Matplotlib name
    # "Terrain". Convert the authentic Matplotlib terrain palette to explicit
    # stop/color pairs accepted by Plotly Surface.
    if palette == "Terrain":
        from matplotlib import colormaps
        from matplotlib.colors import to_hex
        terrain_cmap = colormaps["terrain"]
        surface_scale = [[i / 32, to_hex(terrain_cmap(i / 32))] for i in range(33)]
    else:
        surface_scale = palette
    z0=float(np.nanmin(z))
    fig=go.Figure(go.Surface(x=lon,y=lat,z=z0+(z-z0)*scale,
                            surfacecolor=z,colorscale=surface_scale,connectgaps=False,
                            colorbar=dict(title="m AMSL"),
                            hovertemplate="LON %{x:.5f}<br>LAT %{y:.5f}<br>Relativní Z %{z:.1f}<extra></extra>"))
    # KML geometries are horizontally georeferenced and draped onto nearest DEM elevations.
    from scipy.spatial import cKDTree
    good=np.isfinite(z)
    tree=cKDTree(np.c_[lon[good],lat[good]]) if np.any(good) else None
    heights=z[good]
    # Aggregate vectors into one trace per layer; 30 layers must not create
    # thousands of independent WebGL objects or overwhelm the browser.
    for key,features in layers.items():
        if key not in visible or tree is None:
            continue
        cfg=(styles or {}).get(key,{})
        color=cfg.get("color",PALETTE[0])
        xx,yy,zz=[],[],[]
        mx,my,mz=[],[],[]
        for feature in features[:400]:
            geom=feature.get("geometry") or {}
            typ=geom.get("type")
            paths=[]
            if typ=="LineString":paths=[geom["coordinates"]]
            elif typ=="Polygon":paths=geom["coordinates"]
            elif typ=="MultiPolygon":paths=[ring for poly in geom["coordinates"] for ring in poly]
            elif typ=="Point":paths=[[geom["coordinates"]]]
            elif typ=="MultiLineString":paths=geom["coordinates"]
            for path in paths[:12]:
                if not path:continue
                raw=np.asarray([p[:2] for p in path],dtype=float)
                # Hard cap point density; preserve spatial outline for display.
                if len(raw)>500:
                    raw=raw[np.linspace(0,len(raw)-1,500).astype(int)]
                _,indices=tree.query(raw,k=1)
                elevations=heights[indices]
                surface=z0+(elevations-z0)*scale + max(5.,(float(np.nanmax(z))-z0)*scale*.012)
                if typ=="Point":
                    mx.extend(raw[:,0]);my.extend(raw[:,1]);mz.extend(surface)
                else:
                    xx.extend(raw[:,0]);xx.append(None)
                    yy.extend(raw[:,1]);yy.append(None)
                    zz.extend(surface);zz.append(None)
        if xx:
            fig.add_trace(go.Scatter3d(x=xx,y=yy,z=zz,mode="lines",
                line=dict(color=color,width=max(.5,float(cfg.get("width",2.)))*2),
                name=key,showlegend=True,hoverinfo="name"))
        if mx:
            fig.add_trace(go.Scatter3d(x=mx,y=my,z=mz,mode="markers",
                marker=dict(color=color,size=4),name=key,showlegend=not bool(xx),
                hoverinfo="name"))
    fig.update_layout(template="plotly_dark",paper_bgcolor="#091525",
        title=dict(text=title,font=dict(size=18,color="#e2edff")),
        height=760,margin=dict(l=0,r=0,t=48,b=0),
        scene=dict(xaxis_title="Longitude",yaxis_title="Latitude",
                   zaxis_title="Relative terrain elevation (m)",
                   bgcolor="#10243a",aspectmode="manual",aspectratio=dict(x=1,y=1,z=.45)))
    st.plotly_chart(fig,use_container_width=True)
    st.download_button("EXPORT 3D SCÉNY · INTERAKTIVNÍ HTML",
                       fig.to_html(full_html=True,include_plotlyjs=True).encode("utf-8"),
                       file_name="COVERAGEDIAGRAMS_3D_viewer.html",mime="text/html",
                       use_container_width=True,key="viewer_3d_html_export")
    st.caption("3D: reálné hodnoty DEM, hypsometrie podle výšky AMSL. "
               "Z-exaggerace mění pouze vzhled. Importované vektory se přikládají k nejbližší "
               "vzorkované výšce terénu, nikoli k certifikovanému 3D povrchu.")



def _layer_grid(layers):
    """Dense scrollable grid, constant screen height even for 30+ layers."""
    styles=st.session_state.setdefault("viewer_styles",{})
    for i,key in enumerate(layers):
        styles.setdefault(key,{"show":True,"color":PALETTE[i%len(PALETTE)],
                               "opacity":.4,"width":2.})
    a,b,c=st.columns([3,1,1],gap="small",vertical_alignment="center")
    with a:st.markdown(f"**VRSTVY · {len(layers)}**")
    with b:
        if st.button("VŠE",key="v_all",use_container_width=True):
            for key in layers:styles[key]["show"]=True
            st.session_state["v_grid_version"]=st.session_state.get("v_grid_version",0)+1
            st.rerun()
    with c:
        if st.button("NIC",key="v_none",use_container_width=True):
            for key in layers:styles[key]["show"]=False
            st.session_state["v_grid_version"]=st.session_state.get("v_grid_version",0)+1
            st.rerun()
    if not layers:
        st.caption("Načti KML/KMZ nebo projekt z EDITORU.")
        return set(),{}
    rows=[{"ON":styles[k]["show"],"VRSTVA":k,"#":len(v),
           "HEX":styles[k]["color"],"α":styles[k]["opacity"],"px":styles[k]["width"]}
          for k,v in layers.items()]
    grid=st.data_editor(pd.DataFrame(rows),hide_index=True,num_rows="fixed",
        height=min(490,max(110,45+len(rows)*35)),use_container_width=True,
        key="v_grid_"+str(st.session_state.get("v_grid_version",0)),
        column_config={
            "ON":st.column_config.CheckboxColumn("✓",width="small"),
            "VRSTVA":st.column_config.TextColumn("VRSTVA",disabled=True,width="medium"),
            "#":st.column_config.NumberColumn("#",disabled=True,width="small"),
            "HEX":st.column_config.TextColumn("HEX",width="small"),
            "α":st.column_config.NumberColumn("α",min_value=0.,max_value=1.,step=.05,format="%.2f",width="small"),
            "px":st.column_config.NumberColumn("px",min_value=.5,max_value=10.,step=.5,format="%.1f",width="small"),
        })
    for row in grid.to_dict("records"):
        key=row["VRSTVA"]
        previous=styles[key]
        candidate=str(row["HEX"]).strip()
        styles[key]=dict(show=bool(row["ON"]),
            color=candidate if re.fullmatch(r"#[0-9a-fA-F]{6}",candidate) else previous["color"],
            opacity=max(0.,min(1.,float(row["α"] if pd.notna(row["α"]) else .4))),
            width=max(.5,min(10.,float(row["px"] if pd.notna(row["px"]) else 2.))))
    visible={key for key in layers if styles[key]["show"]}
    st.caption(f"Aktivní {len(visible)} / {len(layers)} · tabulka má vlastní posuvník")
    return visible,{key:styles[key] for key in layers}



def _layer_properties(layers, styles, visible):
    """Inspector is intentionally separate from the dense layer browser."""
    st.markdown('<div class="cd-panel-title">GRAFICKÉ VLASTNOSTI</div>',
                unsafe_allow_html=True)
    names=list(layers)
    if names:
        chosen=st.selectbox("Vybraná vrstva",names,key="viewer_inspected_layer",
                            format_func=lambda x: x if len(x)<40 else x[:37]+"…")
        config=styles[chosen]
        st.caption(f"{len(layers[chosen])} objektů · {('zobrazena' if chosen in visible else 'skrytá')}")
        color=st.color_picker("Barva vrstvy",value=config["color"],
                              key="viewer_property_color_"+chosen+"_"+str(st.session_state.get("viewer_color_refresh",0)))
        opacity=st.slider("Průhlednost",0.,1.,float(config["opacity"]),.05,
                          key="viewer_property_alpha_"+chosen)
        weight=st.slider("Tloušťka linie [px]",.5,10.,float(config["width"]),.5,
                         key="viewer_property_width_"+chosen)
        new=(color,opacity,weight)
        old=(config["color"],config["opacity"],config["width"])
        if new!=old:
            styles[chosen].update(color=color,opacity=opacity,width=weight)
            # Recreate the compact table next rerun to stay synchronized.
            st.session_state["v_grid_version"]=st.session_state.get("v_grid_version",0)+1
        st.markdown('<div class="cd-panel-title">RYCHLÉ PALETY</div>',
                    unsafe_allow_html=True)
        cols=st.columns(4,gap="small")
        for i,c in enumerate(("#5DCDF4","#46E1BE","#F7C66B","#E581DE")):
            with cols[i]:
                if st.button("●",key="viewer_preset_"+str(i)+"_"+chosen,
                             help=c,use_container_width=True):
                    styles[chosen]["color"]=c
                    # Reset picker state before its next render.
                    st.session_state["viewer_color_refresh"]=(
                        st.session_state.get("viewer_color_refresh",0)+1)
                    st.session_state["v_grid_version"]=st.session_state.get("v_grid_version",0)+1
                    st.rerun()
    else:
        st.caption("Vyber nebo naimportuj vrstvu.")
    st.markdown('<div class="cd-panel-title">MAPOVÁ KOMPOZICE</div>',
                unsafe_allow_html=True)
    basemap=st.selectbox("Podklad",list(BASEMAPS),index=0,key="viewer_basemap")
    title=st.text_input("Titulek mapy","RADAR COVERAGE / GEOSPATIAL VIEWER",
                        key="viewer_map_title")
    legend=st.toggle("Legenda",value=True,key="viewer_legend")
    north=st.toggle("Severka",value=True,key="viewer_north")
    return basemap,title,legend,north


def _viewer_legend(layers,visible,styles):
    chunks=[]
    for key in list(layers)[:60]:
        if key not in visible:
            continue
        chunks.append('<div class="v-legrow"><i style="background:'+
                      styles[key]["color"]+'"></i><span>'+html.escape(key)+'</span></div>')
    if not chunks:
        return ""
    return '<div class="v-legend"><b>LAYERS / '+str(len(visible))+'</b>'+''.join(chunks)+'</div>'


def render_viewer():
    from workspace_theme import COMMON_CSS,header
    st.markdown(COMMON_CSS,unsafe_allow_html=True)
    st.markdown("""<style>
    [data-testid="stAppViewContainer"]{background:#0b1626!important}
    .block-container{max-width:100%!important;padding:10px 16px!important}
    [data-testid="stVerticalBlock"]{gap:.36rem!important}
    [data-testid="stDataFrame"]{border:1px solid #3a5571!important;border-radius:8px}
    [data-testid="stButton"] button{min-height:31px!important}
    .v-title{position:absolute;z-index:9999;left:50%;top:15px;transform:translateX(-50%);
      border:1px solid #527294;border-radius:6px;padding:9px 20px;
      background:#07182de8;color:#f3f8ff;font:700 14px system-ui;letter-spacing:.12em;
      white-space:nowrap}
    .v-north{position:absolute;right:20px;top:75px;z-index:9999;color:#f3f8ff;
      font:800 26px system-ui;text-shadow:0 2px 6px #000}
    .v-legend{position:absolute;z-index:9999;left:12px;bottom:24px;
      padding:12px;max-height:340px;overflow:auto;max-width:290px;background:#07182de8;
      border:1px solid #527294;color:#e2ebf7;border-radius:7px;font:11px system-ui}
    .v-legend b{display:block;color:#8bd9fc;margin-bottom:9px;letter-spacing:.1em}
    .v-legrow{display:flex;gap:8px;align-items:center;margin:4px 0;white-space:nowrap}
    .v-legrow span{overflow:hidden;text-overflow:ellipsis}
    .v-legrow i{width:12px;height:9px;flex-shrink:0;border-radius:2px}
    @media(max-width:900px){.v-title{max-width:75%;text-overflow:ellipsis;overflow:hidden}}
    </style>""",unsafe_allow_html=True)
    editor_result,editor_meta=_snapshot()
    ptitle=("RADAR / "+editor_result["config"].radar_mode if editor_result is not None
            else "GEODATA / UNTITLED")
    st.markdown(header("VIEWER",ptitle,"3D · CARTOGRAPHY · PRESENTATION"),
                unsafe_allow_html=True)
    top_left,top_right=st.columns([3,2],gap="small",vertical_alignment="center")
    with top_left:
        st.caption("LAYER STUDIO  /  GEO DATA  /  3D TERRAIN")
    with top_right:
        mode=st.segmented_control("Režim",["2D MAPA","3D TERÉN / HYPSOMETRIE"],
                                  default="2D MAPA",key="viewer_mode",
                                  label_visibility="collapsed",width="stretch")
    editor_meta=editor_meta or {}
    if editor_result is not None:
        st.caption("● EDITOR LINK · výpočty a výškový model převzaty bez přepočtu")
    with st.expander("IMPORT / PROJEKT / SPRÁVA DAT",expanded=False):
        if editor_result is not None:
            st.toggle("Načíst všechny dostupné letové hladiny",value=False,
                      key="viewer_import_all_fl")
        uploads=st.file_uploader("Přidat KML / KMZ / GeoJSON",
            type=["kml","kmz","geojson","json"],accept_multiple_files=True,
            key="viewer_uploads")
        st.caption("KML/KMZ lze kombinovat s výpočtem z EDITORU. Původní vrstvy se nemění.")
    # uploader persists even when expander is closed
    uploads=st.session_state.get("viewer_uploads") or []
    layers=_editor_layers(editor_result,editor_meta) if editor_result is not None else {}
    for file in uploads:
        try:
            for folder,features in _load_layers(file).items():
                layers[f"{file.name} / {folder}"]=features
        except Exception as exc:
            st.warning(f"{file.name}: {exc}")
    center=(editor_result["config"].lat,editor_result["config"].lon) if editor_result is not None else (50.,15.)

    # Stable, symmetric VIEWER studio: layer manager / map canvas / inspector.
    left,canvas,right=st.columns([1.42,4.8,1.55],gap="small")
    with left:
        st.markdown('<div class="cd-panel-title">LAYER MANAGER</div>',unsafe_allow_html=True)
        visible,styles=_layer_grid(layers)
        if layers:
            data={"type":"FeatureCollection","features":[f for key,fs in layers.items()
                  if key in visible for f in fs]}
            st.download_button("⇩ VISIBLE DATA · GEOJSON",
                json.dumps(data,ensure_ascii=False).encode(),
                file_name="COVERAGEDIAGRAMS_viewer.geojson",mime="application/geo+json",
                use_container_width=True)
    with right:
        basemap,title,show_legend,show_north=_layer_properties(layers,styles,visible)
        st.markdown('<div class="cd-panel-title">EXPORT STUDIO</div>',unsafe_allow_html=True)
        st.caption("Vysoké rozlišení a konzistentní zákaznická grafika.")
        fmt=st.segmented_control("Typ výstupu",["PNG","PDF"],default="PNG",
                                 key="viewer_print_format",width="stretch")
        dpi=st.select_slider("Kvalita [DPI]",options=[150,300,600],
                             value=300,key="viewer_print_dpi")
        print_theme=st.radio("Tisková paleta",["NIGHT","LIGHT"],horizontal=True,
                             key="viewer_print_theme")
        if st.button("GENEROVAT MAPOVÝ ATLAS",type="primary",
                     use_container_width=True,key="viewer_export_render"):
            try:
                from viewer_export import render_print
                blob=render_print(layers,styles,title,fmt=fmt.lower(),
                                  dpi=300 if dpi==150 else dpi,
                                  night=print_theme=="NIGHT")
                st.session_state["viewer_print_ready"]=(blob,fmt.lower(),dpi)
            except Exception as exc:
                st.error(f"Tiskový export selhal: {exc}")
        ready=st.session_state.get("viewer_print_ready")
        if ready:
            blob,filetype,quality=ready
            st.download_button("⇩ STÁHNOUT "+filetype.upper(),
                blob,file_name="COVERAGEDIAGRAMS_Map_"+str(quality)+"dpi."+filetype,
                mime="application/pdf" if filetype=="pdf" else "image/png",
                use_container_width=True,key="viewer_print_download")
        st.caption("Tisk obsahuje data a legendu. Online mapové dlaždice "
                   "se do tohoto vektorového výstupu nepřebírají.")
    with canvas:
        if mode=="3D TERÉN / HYPSOMETRIE":
            _three_dimensional(layers,visible,editor_result,center,styles,title)
        else:
            coords=[p for key,features in layers.items() if key in visible
                    for f in features for p in _iter_coords(f.get("geometry"))]
            mapcenter=[float(np.mean([p[1] for p in coords[:2000]])),
                       float(np.mean([p[0] for p in coords[:2000]]))] if coords else list(center)
            m=folium.Map(location=mapcenter,zoom_start=7,tiles=None,control_scale=True,
                         prefer_canvas=True,zoom_animation=False,fade_animation=False)
            url,attr=BASEMAPS[basemap]
            folium.TileLayer(url,attr=attr,name=basemap,max_zoom=19).add_to(m)
            for key,features in layers.items():
                if key not in visible or not features:
                    continue
                cfg=styles[key]
                def style(_feature,cfg=cfg):
                    return {"color":cfg["color"],"weight":cfg["width"],
                            "fillColor":cfg["color"],"fillOpacity":cfg["opacity"]}
                folium.GeoJson({"type":"FeatureCollection","features":features},
                    name=key,style_function=style,
                    tooltip=folium.GeoJsonTooltip(fields=["name"],labels=False)
                    if all("name" in f.get("properties",{}) for f in features) else None).add_to(m)
            if coords:
                lats=[p[1] for p in coords];lons=[p[0] for p in coords]
                m.fit_bounds([[min(lats),min(lons)],[max(lats),max(lons)]])
            legend=_viewer_legend(layers,visible,styles) if show_legend else ""
            overlay='<div class="v-title">'+html.escape(title)+'</div>'
            if show_north:
                overlay+='<div class="v-north">↑ N</div>'
            from branca.element import Element
            m.get_root().html.add_child(Element("""<style>
            .v-title{position:absolute;z-index:9999;left:50%;top:15px;transform:translateX(-50%);
              border:1px solid #527294;border-radius:6px;padding:10px 22px;
              background:#07182de8;color:#f3f8ff;font:700 14px system-ui;letter-spacing:.12em}
            .v-north{position:absolute;right:22px;top:80px;z-index:9999;color:#f3f8ff;
              font:800 26px system-ui;text-shadow:0 2px 6px #000}
            .v-legend{position:absolute;z-index:9999;left:12px;bottom:24px;
              padding:12px;max-height:340px;overflow:auto;max-width:290px;background:#07182de8;
              border:1px solid #527294;color:#e2ebf7;border-radius:7px;font:11px system-ui}
            .v-legend b{display:block;color:#8bd9fc;margin-bottom:9px;letter-spacing:.1em}
            .v-legrow{display:flex;gap:8px;align-items:center;margin:4px 0;white-space:nowrap}
            .v-legrow span{overflow:hidden;text-overflow:ellipsis}
            .v-legrow i{width:12px;height:9px;flex-shrink:0;border-radius:2px}
            </style>"""+overlay+legend))
            folium.LayerControl(collapsed=True).add_to(m)
            Fullscreen().add_to(m)
            MeasureControl(primary_length_unit="kilometers").add_to(m)
            st_folium(m,height=780,use_container_width=True,key="viewer_2d_map",
                      returned_objects=[])
            st.download_button("⇩ MAPA · INTERAKTIVNÍ HTML",
                m.get_root().render().encode("utf-8"),
                file_name="COVERAGEDIAGRAMS_map_viewer.html",mime="text/html",
                use_container_width=True,key="viewer_map_html")
