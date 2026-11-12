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
import hashlib
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
    mode=result["config"].radar_mode
    selected=meta.get("levels",[]) if isinstance(meta,dict) else []
    selected=[ft for ft in selected if core.valid_flight_level(mode,ft)]
    if not selected and not (isinstance(meta,dict) and "levels" in meta):
        selected=list(core.flight_levels_for(mode))[:3]
    if st.session_state.get("viewer_import_all_fl"):
        selected=sorted(set(core.flight_levels_for(mode)).union(selected))
    # Cache expensive polygon generation in the user session. The snapshot
    # token is immutable; the selected flight levels are the only variable.
    signature=(str(st.query_params.get("snapshot","")),tuple(selected))
    previous=st.session_state.get("_viewer_editor_layer_cache")
    if previous and previous[0]==signature:
        return previous[1]
    collections={}
    for ft in selected:
        try:
            collections["RADAR / "+core.level_label(ft)]=coverage_geojson(result,ft).get("features",[])
        except Exception as exc:
            st.warning(f"Vrstva {ft} ft není dostupná: {exc}")
    st.session_state["_viewer_editor_layer_cache"]=(signature,collections)
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
                opacity=max(0.,min(1.,float(cfg.get("opacity",.4)))),
                name=key,showlegend=True,hoverinfo="name"))
        if mx:
            fig.add_trace(go.Scatter3d(x=mx,y=my,z=mz,mode="markers",
                marker=dict(color=color,size=4),
                opacity=max(0.,min(1.,float(cfg.get("opacity",.4)))),
                name=key,showlegend=not bool(xx),
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



def _load_uploaded_layers(upload):
    """Parsing uploaded KML/KMZ is a cache miss only on new file content."""
    blob=upload.getvalue()
    key=(upload.name,hashlib.blake2b(blob,digest_size=16).hexdigest())
    cache=st.session_state.setdefault("_viewer_upload_cache",{})
    if key not in cache:
        cache[key]=_load_layers(upload)
        # Bound memory when the user replaces files repeatedly.
        while len(cache)>12:
            cache.pop(next(iter(cache)))
    return cache[key]


def _get_2d_map(layers, styles, visible, basemap, title, show_legend, show_north, center):
    """Reuse Folium objects on Streamlit reruns that do not affect map content.

    30+ layer polygon serialization is done once per visual change, not on
    every UI interaction. Layers must be stable objects from the caches above.
    """
    signature=(
        tuple((key,id(layers[key]),len(layers[key]),
               styles[key].get("color"),styles[key].get("width"),
               styles[key].get("opacity")) for key in layers if key in visible),
        basemap,title,show_legend,show_north,tuple(center),
    )
    cached=st.session_state.get("_viewer_folium_cache")
    if cached is not None and cached[0]==signature:
        return cached[1]
    coords=[p for key,features in layers.items() if key in visible
            for f in features for p in _iter_coords(f.get("geometry"))]
    mapcenter=([float(np.mean([p[1] for p in coords[:2000]])),
                float(np.mean([p[0] for p in coords[:2000]]))]
               if coords else list(center))
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
    # The fixed layer grid already controls visibility. A second Leaflet
    # LayerControl would duplicate state and can cause inconsistent toggles.
    Fullscreen().add_to(m)
    MeasureControl(primary_length_unit="kilometers").add_to(m)
    st.session_state["_viewer_folium_cache"]=(signature,m)
    return m


def _cached_map_html(m):
    cached=st.session_state.get("_viewer_html_cache")
    if cached and cached[0] is m:
        return cached[1]
    page=m.get_root().render().encode("utf-8")
    st.session_state["_viewer_html_cache"]=(m,page)
    return page


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
    # One very compact row per layer. Styling belongs in the right inspector,
    # never in six cramped columns next to a 3D canvas.
    rows=[{"ON":styles[k]["show"],"VRSTVA":k,"#":len(v)}
          for k,v in layers.items()]
    grid=st.data_editor(pd.DataFrame(rows),hide_index=True,num_rows="fixed",
        height=min(490,max(110,45+len(rows)*32)),use_container_width=True,
        key="v_grid_"+str(st.session_state.get("v_grid_version",0)),
        column_config={
            "ON":st.column_config.CheckboxColumn("✓",width="small"),
            "VRSTVA":st.column_config.TextColumn("VRSTVA",disabled=True,width="large"),
            "#":st.column_config.NumberColumn("#",disabled=True,width="small"),
        })
    for row in grid.to_dict("records"):
        styles[row["VRSTVA"]]["show"]=bool(row["ON"])
    visible={key for key in layers if styles[key]["show"]}
    st.caption(f"Aktivní {len(visible)} / {len(layers)} · upravuj vybranou vrstvu vpravo")
    return visible,{key:styles[key] for key in layers}



_STYLE_PRESETS = {
    "Vlastní barva": None,
    "Cyan · #5DCDF4": "#5DCDF4",
    "Mint · #46E1BE": "#46E1BE",
    "Amber · #F7C66B": "#F7C66B",
    "Magenta · #E581DE": "#E581DE",
}


def _layer_properties(layers, styles, visible):
    """Transactional layer styling: apply only once, not on every slider move.

    The selected layer stays outside the form so switching the inspector does
    not accidentally commit unsaved settings from another layer.
    """
    st.markdown('<div class="cd-panel-title">GRAFICKÉ VLASTNOSTI</div>',
                unsafe_allow_html=True)
    names=list(layers)
    if names:
        chosen=st.selectbox("Vybraná vrstva",names,key="viewer_inspected_layer",
                            format_func=lambda x: x if len(x)<40 else x[:37]+"…")
        cfg=styles[chosen]
        st.caption(f"{len(layers[chosen])} objektů · "
                   f"{'zobrazena' if chosen in visible else 'skrytá'}")
        # Input keys change only after applying or loading a workspace. This
        # avoids stale color-picker state overriding loaded/saved layer styles.
        revision=st.session_state.get("viewer_style_revision",0)
        key_suffix=f"{revision}_{names.index(chosen)}"
        with st.form("viewer_style_editor",clear_on_submit=False,
                     enter_to_submit=False,border=False):
            color_col,preset_col=st.columns([1,3],gap="small",
                                             vertical_alignment="bottom")
            with color_col:
                color=st.color_picker("Barva",value=cfg["color"],
                    key="viewer_form_color_"+key_suffix)
            with preset_col:
                preset=st.selectbox("Paleta",list(_STYLE_PRESETS),
                    index=0,key="viewer_form_preset_"+key_suffix,
                    help="Vybraný preset má přednost před vlastní barvou.")
            op_col,line_col=st.columns(2,gap="small")
            with op_col:
                opacity_percent=st.number_input("Výplň [%]",min_value=0,
                    max_value=100,value=int(round(float(cfg["opacity"])*100)),
                    step=5,key="viewer_form_opacity_"+key_suffix)
            with line_col:
                weight=st.number_input("Linie [px]",min_value=.5,max_value=10.,
                    value=float(cfg["width"]),step=.5,format="%.1f",
                    key="viewer_form_weight_"+key_suffix)
            submitted=st.form_submit_button("POUŽÍT STYL",type="primary",
                                            use_container_width=True)
        if submitted:
            selected_color=_STYLE_PRESETS[preset] or color
            cfg.update(color=selected_color,opacity=opacity_percent/100.,
                       width=float(weight))
            st.session_state["viewer_style_revision"]=revision+1
            # Exactly one rerun after an explicit apply, rather than on slider
            # changes. Existing render/print code reads styles from this dict.
            st.rerun()
    else:
        st.caption("Vyber nebo naimportuj vrstvu.")
    with st.expander("MAPOVÁ KOMPOZICE",expanded=False):
        basemap=st.selectbox("Podklad",list(BASEMAPS),index=0,
                             key="viewer_basemap")
        title=st.text_input("Titulek mapy","RADAR COVERAGE / GEOSPATIAL VIEWER",
                            key="viewer_map_title")
        a,b=st.columns(2,gap="small")
        with a:
            legend=st.toggle("Legenda",value=True,key="viewer_legend")
        with b:
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


def _restore_viewer_workspace():
    """Uploader callback runs before widgets are instantiated this rerun."""
    upload=st.session_state.get("viewer_project_upload")
    if upload is None:
        return
    try:
        from viewer_workspace_file import load_workspace
        layers,styles,settings=load_workspace(upload.getvalue())
        st.session_state["viewer_imported_workspace_layers"]=layers
        st.session_state["viewer_styles"]=styles
        st.session_state["viewer_style_revision"]=st.session_state.get("viewer_style_revision",0)+1
        allowed={"viewer_mode":("2D MAPA","3D TERÉN / HYPSOMETRIE"),
                 "viewer_basemap":tuple(BASEMAPS)}
        for key,choices in allowed.items():
            value=settings.get(key)
            if value in choices:
                st.session_state[key]=value
        for key in ("viewer_map_title","viewer_legend","viewer_north"):
            if key in settings:
                value=settings[key]
                if (key=="viewer_map_title" and isinstance(value,str)) or (
                    key!="viewer_map_title" and isinstance(value,bool)):
                    st.session_state[key]=value
        st.session_state["viewer_workspace_notice"]="VIEWER projekt načten včetně vrstev a grafických vlastností."
        st.session_state.pop("viewer_workspace_error",None)
        st.session_state["v_grid_version"]=st.session_state.get("v_grid_version",0)+1
    except Exception as exc:
        st.session_state["viewer_workspace_error"]=str(exc)


@st.fragment
def _viewer_export_panel(layers,styles,title,mode,basemap,show_legend,show_north):
    """Export controls rerun independently; they never redraw Leaflet."""
    with st.expander("EXPORT STUDIO · PNG / PDF / CDVIEW",expanded=False):
        fmt=st.segmented_control("Typ výstupu",["PNG","PDF"],default="PNG",
                                 key="viewer_print_format",width="stretch")
        dpi=st.select_slider("Kvalita [DPI]",options=[300,600],
                             value=300,key="viewer_print_dpi")
        print_theme=st.radio("Tisková paleta",["NIGHT","LIGHT"],horizontal=True,
                             key="viewer_print_theme")
        if st.button("GENEROVAT MAPOVÝ ATLAS",type="primary",
                     use_container_width=True,key="viewer_export_render"):
            try:
                from viewer_export import render_print
                blob=render_print(layers,styles,title,fmt=fmt.lower(),
                                  dpi=dpi,
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
        st.divider()
        if st.button("ULOŽIT ROZLOŽENÍ · CDVIEW",
                     key="viewer_workspace_save",use_container_width=True):
            try:
                from viewer_workspace_file import make_workspace
                st.session_state["viewer_workspace_bytes"]=make_workspace(
                    layers,styles,{"viewer_mode":mode,
                                   "viewer_basemap":basemap,
                                   "viewer_map_title":title,
                                   "viewer_legend":show_legend,
                                   "viewer_north":show_north})
            except Exception as exc:
                st.error(f"VIEWER projekt nelze uložit: {exc}")
        if st.session_state.get("viewer_workspace_bytes"):
            st.download_button("⇩ STÁHNOUT CDVIEW",
                data=st.session_state["viewer_workspace_bytes"],
                file_name="COVERAGEDIAGRAMS_viewer.cdview",
                mime="application/octet-stream",use_container_width=True,
                key="viewer_workspace_download")


def render_viewer():
    from workspace_theme import COMMON_CSS
    st.markdown(COMMON_CSS,unsafe_allow_html=True)
    st.markdown("""<style>
    [data-testid="stAppViewContainer"]{background:#0b1626!important}
    .block-container{max-width:100%!important;padding:10px 16px!important}
    [data-testid="stVerticalBlock"]{gap:.36rem!important}
    [data-testid="stDataFrame"]{border:1px solid #3a5571!important;border-radius:8px}
    [data-testid="stButton"] button{min-height:31px!important}
    /* Streamlit renders dropdown popovers outside the VIEWER columns.
       Style inputs and overlay menus explicitly instead of inheriting the
       white BaseWeb control backgrounds from the light app theme. */
    [data-testid="stAppViewContainer"] div[data-baseweb="select"] > div,
    [data-testid="stAppViewContainer"] div[data-baseweb="input"] > div,
    [data-testid="stAppViewContainer"] div[data-baseweb="input"]{
      background:#172d44!important;border-color:#40627d!important;
      color:#eaf4ff!important}
    [data-testid="stAppViewContainer"] div[data-baseweb="select"] *,
    [data-testid="stAppViewContainer"] div[data-baseweb="input"] input,
    [data-testid="stAppViewContainer"] div[data-baseweb="select"] input,
    [data-testid="stAppViewContainer"] input[type="text"]{
      color:#eaf4ff!important;-webkit-text-fill-color:#eaf4ff!important}
    [data-testid="stAppViewContainer"] input::placeholder{
      color:#a2bbce!important;-webkit-text-fill-color:#a2bbce!important}
    [data-baseweb="popover"] [role="listbox"],
    [data-baseweb="popover"] [data-baseweb="menu"],
    [data-baseweb="popover"] [data-baseweb="select"]{
      background:#142940!important;color:#eaf4ff!important;
      border:1px solid #40627d!important}
    [data-baseweb="popover"] [role="option"],
    [data-baseweb="popover"] [role="listbox"] li,
    [data-baseweb="menu"] [role="option"]{
      background:#142940!important;color:#eaf4ff!important;
      -webkit-text-fill-color:#eaf4ff!important}
    [data-baseweb="popover"] [role="option"]:hover,
    [data-baseweb="popover"] [aria-selected="true"]{
      background:#255173!important;color:#ffffff!important}
    [data-baseweb="popover"] [role="option"] *,
    [data-baseweb="popover"] [role="listbox"] *{
      color:#eaf4ff!important;-webkit-text-fill-color:#eaf4ff!important}
    /* Persistent, visible 2D / 3D toolbar above map. */
    .st-key-viewer_mode_toolbar{
      background:#11263b!important;border:1px solid #355773!important;
      border-radius:7px!important;padding:6px 12px!important;
      margin-bottom:5px!important}
    .st-key-viewer_mode_toolbar [data-testid="stMarkdown"] p{
      color:#c9ebff!important;letter-spacing:.07em!important;font-size:12px!important}
    .st-key-viewer_mode_toolbar button{
      background:#1c3853!important;border:1px solid #507393!important;
      color:#edf7ff!important;-webkit-text-fill-color:#edf7ff!important;
      font-weight:750!important;font-size:12px!important;min-height:37px!important;
      opacity:1!important}
    .st-key-viewer_mode_toolbar button[kind="primary"]{
      background:#2563c7!important;border-color:#5392ff!important;
      color:#fff!important;-webkit-text-fill-color:#fff!important}
    .st-key-viewer_mode_toolbar button:hover{
      border-color:#89d9ff!important;background:#24577b!important}
    /* Compact inspection console: 2 numeric settings per row, no giant
       sliders and no repeated full-width card paddings. */
    .st-key-viewer_inspector [data-testid="stVerticalBlock"]{gap:.25rem!important}
    .st-key-viewer_inspector [data-testid="stForm"]{
      padding:4px 0!important;margin:0!important;background:transparent!important;
      border:none!important}
    .st-key-viewer_inspector [data-testid="stWidgetLabel"] p{
      font-size:11px!important;line-height:1.1!important;margin-bottom:0!important}
    .st-key-viewer_inspector [data-testid="stNumberInput"] input{
      min-height:29px!important;font-size:12px!important}
    .st-key-viewer_inspector [data-testid="stSelectbox"]{
      margin-bottom:0!important}
    .st-key-viewer_inspector [data-testid="stExpander"]{
      margin:3px 0!important}
    .st-key-viewer_inspector [data-testid="stExpander"] summary{
      min-height:32px!important;font-size:11px!important}
    .st-key-viewer_inspector [data-testid="stColorPicker"]{
      min-width:46px!important}
    [data-testid="stAppViewContainer"] [data-testid="stForm"]{
      border:1px solid #304e68!important;border-radius:9px!important;
      background:#11243a!important;padding:11px!important}

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
    # The main 2D workstation is one persistent, browser-controlled canvas.
    # Streamlit never receives checkbox/slider/pan events from this viewer.
    if st.query_params.get("viewer3d") != "1" and st.query_params.get("studio") != "1":
        from viewer_fullscreen import render_fullscreen_viewer
        editor_meta=editor_meta or {}
        layers=_editor_layers(editor_result,editor_meta) if editor_result is not None else {}
        layers.update(st.session_state.get("viewer_imported_workspace_layers") or {})
        center=(editor_result["config"].lat,editor_result["config"].lon) if editor_result is not None else (50.,15.)
        styles=st.session_state.get("viewer_styles") or {}
        # Preserve the one-time EDITOR -> VIEWER snapshot token on mode changes.
        from urllib.parse import urlencode
        params={"viewer":"1","viewer3d":"1"}
        if st.query_params.get("snapshot"):
            params["snapshot"]=str(st.query_params["snapshot"])
        print_params={"viewer":"1","studio":"1"}
        if st.query_params.get("snapshot"):
            print_params["snapshot"]=str(st.query_params["snapshot"])
        render_fullscreen_viewer(layers,styles,center,
            diagnostic_result=editor_result, diagnostic_levels=(editor_meta or {}).get("levels", []),
            snapshot=str(st.query_params.get("snapshot","")),
            three_d_url="?"+urlencode(params),
            studio_url="?"+urlencode(print_params))
        return
    if st.query_params.get("viewer3d") == "1":
        st.session_state["viewer_mode"]="3D TERÉN / HYPSOMETRIE"
    # Explicit, high-contrast view controls: the previous segmented control
    # was visually lost under the global dark Streamlit theme.
    with st.container(key="viewer_mode_toolbar"):
        caption_col,map_col,terrain_col=st.columns([3.2,1.25,1.9],
                                                    gap="small",
                                                    vertical_alignment="center")
        with caption_col:
            st.markdown("**VIEWER · PROSTOROVÉ ZOBRAZENÍ**")
        current_mode=st.session_state.get("viewer_mode","2D MAPA")
        with map_col:
            if st.button("▧  2D MAPA",key="viewer_mode_2d_btn",
                         use_container_width=True,
                         type="primary" if current_mode=="2D MAPA" else "secondary"):
                st.session_state["viewer_mode"]="2D MAPA"
                st.query_params.pop("viewer3d",None)
                st.rerun()
        with terrain_col:
            if st.button("◈  3D TERÉN / HYPSOMETRIE",key="viewer_mode_3d_btn",
                         use_container_width=True,
                         type="primary" if current_mode=="3D TERÉN / HYPSOMETRIE" else "secondary"):
                st.session_state["viewer_mode"]="3D TERÉN / HYPSOMETRIE"
                st.rerun()
    mode=st.session_state.get("viewer_mode","2D MAPA")
    editor_meta=editor_meta or {}
    if editor_result is not None:
        st.caption("● EDITOR LINK · výpočty a výškový model převzaty bez přepočtu")
    with st.expander("IMPORT / PROJEKT / SPRÁVA DAT",expanded=False):
        project_upload=st.file_uploader("Otevřít uložené rozložení · CDVIEW",
            type=["cdview"],key="viewer_project_upload",
            on_change=_restore_viewer_workspace)
        if st.session_state.get("viewer_workspace_error"):
            st.error(st.session_state["viewer_workspace_error"])
        elif st.session_state.get("viewer_workspace_notice"):
            st.success(st.session_state["viewer_workspace_notice"])
        if editor_result is not None:
            st.toggle("Načíst všechny dostupné letové hladiny",value=False,
                      key="viewer_import_all_fl")
        uploads=st.file_uploader("Přidat KML / KMZ / GeoJSON",
            type=["kml","kmz","geojson","json"],accept_multiple_files=True,
            key="viewer_uploads")
        st.caption("CDVIEW ukládá vrstvy a vzhled; CDPROJ ukládá výpočet a DEM.")
    # uploader persists even when expander is closed
    uploads=st.session_state.get("viewer_uploads") or []
    layers=_editor_layers(editor_result,editor_meta) if editor_result is not None else {}
    layers.update(st.session_state.get("viewer_imported_workspace_layers") or {})
    for file in uploads:
        try:
            for folder,features in _load_uploaded_layers(file).items():
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
        with st.container(key="viewer_inspector"):
            basemap,title,show_legend,show_north=_layer_properties(
                layers,styles,visible)
            _viewer_export_panel(layers,styles,title,mode,basemap,
                                 show_legend,show_north)
    with canvas:
        if mode=="3D TERÉN / HYPSOMETRIE":
            _three_dimensional(layers,visible,editor_result,center,styles,title)
        else:
            m=_get_2d_map(layers,styles,visible,basemap,title,
                          show_legend,show_north,center)
            # Stable component key and unchanged Folium object on unrelated
            # widget events. No browser-to-Streamlit map event feedback loop.
            st_folium(m,height=780,use_container_width=True,key="viewer_2d_map",
                      returned_objects=[])
            st.download_button("⇩ MAPA · INTERAKTIVNÍ HTML",
                _cached_map_html(m),
                file_name="COVERAGEDIAGRAMS_map_viewer.html",mime="text/html",
                use_container_width=True,key="viewer_map_html")
