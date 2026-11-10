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


def _three_dimensional(layers, visible):
    import plotly.graph_objects as go
    dem=st.file_uploader("Výškový model · GeoTIFF / DEM (WGS84 i projektovaný CRS)",
                         type=["tif","tiff"],key="viewer_dem")
    if dem is None:
        st.info("Pro skutečný 3D terén a hypsometrii nahraj GeoTIFF s nadmořskou výškou. "
                "Bez DEM aplikace nevymýšlí výšky z 2D mapy.")
        return
    try:
        lon,lat,z=_dem_from_bytes(dem.getvalue())
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
    uploads=st.file_uploader("NAČÍST MAPOVÉ VRSTVY",type=["kml","kmz","geojson","json"],
                             accept_multiple_files=True,key="viewer_uploads")
    layers={}
    for file in uploads or []:
        try:
            for folder,features in _load_layers(file).items():
                layers[f"{file.name} / {folder}"]=features
        except Exception as exc:
            st.warning(f"{file.name}: {exc}")
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
            _three_dimensional(layers,visible)
        else:
            coords=[p for key,features in layers.items() if key in visible
                    for f in features for p in _iter_coords(f.get("geometry"))]
            center=[float(np.mean([p[1] for p in coords[:2000]])),
                    float(np.mean([p[0] for p in coords[:2000]]))] if coords else [50.0,15.0]
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
