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
import streamlit as st
from folium.plugins import Fullscreen, MeasureControl
from streamlit_folium import st_folium

K = "{http://www.opengis.net/kml/2.2}"
BASEMAPS = {
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


def _three_dimensional(layers, visible, editor_result=None, center=(50.,15.)):
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
    z0=float(np.nanmin(z))
    fig=go.Figure(go.Surface(x=lon,y=lat,z=z0+(z-z0)*scale,
                            surfacecolor=z,colorscale=palette,connectgaps=False,
                            colorbar=dict(title="m AMSL"),
                            hovertemplate="LON %{x:.5f}<br>LAT %{y:.5f}<br>Relativní Z %{z:.1f}<extra></extra>"))
    # KML geometries are horizontally georeferenced and draped onto nearest DEM elevations.
    from scipy.spatial import cKDTree
    good=np.isfinite(z)
    tree=cKDTree(np.c_[lon[good],lat[good]]) if np.any(good) else None
    heights=z[good]
    for key,features in layers.items():
        if key not in visible or tree is None:
            continue
        color=st.session_state.get("viewer_color_"+key,PALETTE[0])
        for feature in features[:350]:
            geom=feature.get("geometry") or {}
            typ=geom.get("type")
            paths=[]
            if typ=="LineString":paths=[geom["coordinates"]]
            elif typ=="Polygon":paths=geom["coordinates"]
            elif typ=="MultiPolygon":paths=[ring for poly in geom["coordinates"] for ring in poly]
            elif typ=="Point":paths=[[geom["coordinates"]]]
            for path in paths:
                if not path:continue
                xy=np.asarray([p[:2] for p in path],dtype=float)
                _,indices=tree.query(xy,k=1)
                elev=heights[indices]
                zz=z0+(elev-z0)*scale + max(5.0, (float(np.nanmax(z))-z0)*scale*.012)
                fig.add_trace(go.Scatter3d(x=xy[:,0],y=xy[:,1],z=zz,
                    mode="markers" if typ=="Point" else "lines",line=dict(color=color,width=6),
                    marker=dict(color=color,size=4),name=key,showlegend=False,
                    hovertext=feature.get("properties",{}).get("name",key)))
    fig.update_layout(height=700,margin=dict(l=0,r=0,t=10,b=0),
        scene=dict(xaxis_title="Longitude",yaxis_title="Latitude",
                   zaxis_title="Relative terrain elevation (m)",
                   aspectmode="manual",aspectratio=dict(x=1,y=1,z=.45)))
    st.plotly_chart(fig,use_container_width=True)
    st.download_button("EXPORT 3D SCÉNY · INTERAKTIVNÍ HTML",
                       fig.to_html(full_html=True,include_plotlyjs=True).encode("utf-8"),
                       file_name="COVERAGEDIAGRAMS_3D_viewer.html",mime="text/html",
                       use_container_width=True,key="viewer_3d_html_export")
    st.caption("3D: reálné hodnoty DEM, hypsometrie podle výšky AMSL. "
               "Z-exaggerace mění pouze vzhled. Importované vektory se přikládají k nejbližší "
               "vzorkované výšce terénu, nikoli k certifikovanému 3D povrchu.")


def render_viewer():
    st.markdown("""<style>
      [data-testid="stAppViewContainer"]{background:#f3f6fb}
      .block-container{max-width:100%;padding:12px 20px}
    </style>""",unsafe_allow_html=True)
    st.markdown("### COVERAGEDIAGRAMS  /  VIEWER")
    st.caption("Samostatné okno integrované v aplikaci · KML / KMZ / GeoJSON · 2D / 3D · bez radarového přepočtu")
    editor_result,editor_meta=_snapshot()
    if editor_result is not None:
        st.success("Vypočtené krytí a vzorkovaný DEM převzaty z EDITORU bez dalšího nahrávání.")
        st.toggle("Načíst všechny dostupné letové hladiny",value=False,key="viewer_import_all_fl")
    else:
        st.caption("Bez otevřeného projektu můžeš přidat KML/KMZ a stáhnout vlastní DEM.")
    uploads=st.file_uploader("NAČÍST MAPOVÉ VRSTVY",type=["kml","kmz","geojson","json"],
                             accept_multiple_files=True,key="viewer_uploads")
    layers=_editor_layers(editor_result,editor_meta) if editor_result is not None else {}
    for file in uploads or []:
        try:
            for folder,features in _load_layers(file).items():
                layers[f"{file.name} / {folder}"]=features
        except Exception as exc:
            st.warning(f"{file.name}: {exc}")
    editor_center=(editor_result["config"].lat,editor_result["config"].lon) if editor_result is not None else (50.,15.)
    sidebar,maparea=st.columns([1,4],gap="medium")
    with sidebar:
        st.markdown("**SPRÁVCE VRSTEV**")
        visible=set()
        for i,(key,features) in enumerate(layers.items()):
            st.caption(f"{key} · {len(features)} objektů")
            if st.checkbox("Zobrazit",value=True,key="viewer_show_"+key):
                visible.add(key)
            st.color_picker("Barva",PALETTE[i%len(PALETTE)],key="viewer_color_"+key)
        opacity=st.slider("Průhlednost výplně",0.0,1.0,0.35,0.05,key="viewer_opacity")
        basemap=st.selectbox("Mapový podklad",list(BASEMAPS),key="viewer_basemap")
        if layers:
            fc={"type":"FeatureCollection","features":[f for k,fs in layers.items() if k in visible for f in fs]}
            st.download_button("EXPORT VIDITELNÝCH VRSTEV · GEOJSON",json.dumps(fc,ensure_ascii=False).encode(),
                               file_name="COVERAGEDIAGRAMS_viewer.geojson",
                               mime="application/geo+json",use_container_width=True)
    with maparea:
        mode=st.radio("REŽIM ZOBRAZENÍ",["2D MAPA","3D TERÉN / HYPSOMETRIE"],horizontal=True)
        if mode=="3D TERÉN / HYPSOMETRIE":
            _three_dimensional(layers,visible,editor_result,editor_center)
        else:
            coords=[p for key,features in layers.items() if key in visible
                    for f in features for p in _iter_coords(f.get("geometry"))]
            center=[float(np.mean([p[1] for p in coords[:2000]])),
                    float(np.mean([p[0] for p in coords[:2000]]))] if coords else list(editor_center)
            m=folium.Map(location=center,zoom_start=7,tiles=None,control_scale=True)
            url,attr=BASEMAPS[basemap]
            folium.TileLayer(url,attr=attr,name=basemap,max_zoom=19).add_to(m)
            for key,features in layers.items():
                if key not in visible:continue
                color=st.session_state.get("viewer_color_"+key,PALETTE[0])
                def style(_feature,color=color,opacity=opacity):
                    return {"color":color,"weight":2,"fillColor":color,"fillOpacity":opacity}
                folium.GeoJson({"type":"FeatureCollection","features":features},name=key,
                               style_function=style,tooltip=folium.GeoJsonTooltip(
                                fields=["name"],aliases=["Name:"],sticky=True) if features and
                               all("name" in f.get("properties",{}) for f in features) else None).add_to(m)
            if coords:
                lats=[p[1] for p in coords];lons=[p[0] for p in coords]
                m.fit_bounds([[min(lats),min(lons)],[max(lats),max(lons)]])
            folium.LayerControl(collapsed=True).add_to(m)
            Fullscreen().add_to(m)
            MeasureControl(primary_length_unit="kilometers").add_to(m)
            st_folium(m,height=740,use_container_width=True,key="viewer_2d_map",
                      returned_objects=[])
            st.caption("Výběr vrstev a základní kartografie. Tiskový PNG/PDF layout bude následovat.")
