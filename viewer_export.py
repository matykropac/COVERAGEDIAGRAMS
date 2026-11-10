"""High-resolution print composition from selected VIEWER vector layers.

Print output is deliberately labeled VECTOR MAP: it does not misrepresent
online basemap tiles as included offline raster imagery.
"""
from __future__ import annotations
from io import BytesIO
import math

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.patches import Polygon as MplPolygon
from pyproj import Transformer


def _shapes(geom):
    if not isinstance(geom,dict):
        return
    t=geom.get("type")
    coords=geom.get("coordinates",[])
    if t=="GeometryCollection":
        for g in geom.get("geometries",[]):
            yield from _shapes(g)
    elif t=="Point":
        yield "point",[coords]
    elif t=="MultiPoint":
        yield "point",coords
    elif t=="LineString":
        yield "line",coords
    elif t=="MultiLineString":
        for line in coords:
            yield "line",line
    elif t=="Polygon":
        for i,ring in enumerate(coords):
            yield ("polygon" if i==0 else "hole"),ring
    elif t=="MultiPolygon":
        for poly in coords:
            for i,ring in enumerate(poly):
                yield ("polygon" if i==0 else "hole"),ring


def render_print(layers,styles,title,*,fmt="png",dpi=300,night=True):
    """Compose 2D WGS84 features on a metric web-Mercator design canvas."""
    if fmt not in ("png","pdf") or dpi not in (300,600):
        raise ValueError("Nepodporovaný typ nebo rozlišení exportu.")
    selected=[(key,features,styles[key]) for key,features in layers.items()
              if styles.get(key,{}).get("show",False)]
    if not selected:
        raise ValueError("Vyber alespoň jednu viditelnou vrstvu.")
    transformer=Transformer.from_crs("EPSG:4326","EPSG:3857",always_xy=True)
    records=[]
    minx=miny=float("inf")
    maxx=maxy=float("-inf")
    points=0
    for key,features,cfg in selected:
        for feature in features[:2500]:
            for kind,raw in _shapes((feature or {}).get("geometry",{})):
                if not raw:
                    continue
                arr=np.asarray([p[:2] for p in raw if len(p)>=2],dtype=float)
                if arr.ndim!=2 or arr.shape[1]!=2 or not len(arr):
                    continue
                arr=arr[np.isfinite(arr).all(axis=1)]
                arr=arr[(np.abs(arr[:,0])<=180)&(np.abs(arr[:,1])<85)]
                if not len(arr):
                    continue
                if len(arr)>800:
                    arr=arr[np.linspace(0,len(arr)-1,800).astype(int)]
                xx,yy=transformer.transform(arr[:,0],arr[:,1])
                xy=np.column_stack([xx,yy])
                if not np.isfinite(xy).all():
                    continue
                minx=min(minx,float(np.min(xx)));maxx=max(maxx,float(np.max(xx)))
                miny=min(miny,float(np.min(yy)));maxy=max(maxy,float(np.max(yy)))
                records.append((kind,xy,cfg))
                points+=len(xy)
                if points>1_200_000:
                    raise ValueError("Pro tiskovou kompozici je příliš mnoho geometrických bodů.")
    if not records:
        raise ValueError("Viditelné vrstvy neobsahují vykreslitelnou geometrii.")
    dark_bg="#0b1728" if night else "#ffffff"
    ink="#e7f4ff" if night else "#1b324b"
    subtle="#8ca9c4" if night else "#526b82"
    grid="#25425a" if night else "#e2e8f0"
    fig=Figure(figsize=(14,9),dpi=dpi,facecolor=dark_bg)
    FigureCanvasAgg(fig)
    ax=fig.add_axes([.065,.12,.78,.76],facecolor=dark_bg)
    extent=max(maxx-minx,maxy-miny,10000.)
    padx=max((maxx-minx)*.075,extent*.025)
    pady=max((maxy-miny)*.075,extent*.025)
    ax.set_xlim(minx-padx,maxx+padx)
    ax.set_ylim(miny-pady,maxy+pady)
    ax.set_aspect("equal",adjustable="datalim")
    ax.grid(True,color=grid,linewidth=.5,alpha=.55,zorder=0)
    ax.tick_params(colors=subtle,labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(grid)
    ax.ticklabel_format(style="plain",useOffset=False)
    for kind,xy,cfg in records:
        color=cfg.get("color","#62c9e9")
        alpha=max(0.,min(1.,float(cfg.get("opacity",.4))))
        weight=max(.3,min(8.,float(cfg.get("width",2.))))
        if kind=="point":
            ax.scatter(xy[:,0],xy[:,1],s=12*weight,color=color,alpha=.95,zorder=4)
        elif kind=="line":
            ax.plot(xy[:,0],xy[:,1],color=color,linewidth=weight,alpha=.95,zorder=3)
        elif len(xy)>=3:
            ax.add_patch(MplPolygon(xy,closed=True,
                facecolor=(color if kind=="polygon" else dark_bg),
                edgecolor=color if kind=="polygon" else dark_bg,
                linewidth=max(.3,weight*.6),alpha=alpha if kind=="polygon" else 1,zorder=2))
    fig.text(.065,.95,(title.strip() or "COVERAGEDIAGRAMS MAP").upper(),
             color=ink,fontsize=19,weight="bold")
    fig.text(.065,.918,"COVERAGEDIAGRAMS  /  GEOSPATIAL VISUALIZATION",fontsize=9,
             color=subtle,weight="bold")
    fig.text(.91,.83,"N",fontsize=15,weight="bold",color=ink,ha="center")
    fig.text(.91,.795,"↑",fontsize=30,weight="bold",color="#63c9ef",ha="center")
    fig.text(.87,.72,"LAYERS",fontsize=10,color="#63c9ef",weight="bold")
    for i,(key,features,cfg) in enumerate(selected[:19]):
        y=.69-i*.029
        fig.text(.872,y,"━",fontsize=14,color=cfg.get("color","#63c9ef"))
        shown=str(key)
        if len(shown)>29:
            shown=shown[:26]+"..."
        fig.text(.892,y,shown,fontsize=7.1,color=ink,va="baseline")
    if len(selected)>19:
        fig.text(.875,.11,f"+ {len(selected)-19} OTHER LAYERS",fontsize=8,color=subtle)
    width_m=maxx-minx
    scale_km=max(1,int(math.ceil(max(1,width_m)/5/1000)))
    scale_m=scale_km*1000
    if scale_m<width_m*.7:
        x0=minx+padx*.3;y0=miny-pady*.4
        ax.plot([x0,x0+scale_m],[y0,y0],color=ink,linewidth=3,solid_capstyle="butt")
        ax.plot([x0,x0],[y0-extent*.008,y0+extent*.008],color=ink,linewidth=2)
        ax.plot([x0+scale_m,x0+scale_m],[y0-extent*.008,y0+extent*.008],
                color=ink,linewidth=2)
        ax.text(x0,y0+extent*.013,"0",color=ink,fontsize=8)
        ax.text(x0+scale_m,y0+extent*.013,f"{scale_km} km",color=ink,
                fontsize=8,ha="right")
    fig.text(.065,.044,"WGS84 SOURCE GEOMETRIES  ·  WEB MERCATOR PRINT VIEW  ·  VECTOR DATA ONLY",
             color=subtle,fontsize=8)
    fig.text(.065,.022,"Basemap tiles not embedded. For engineering presentation, not navigation.",
             color=subtle,fontsize=7)
    output=BytesIO()
    try:
        fig.savefig(output,format=fmt,dpi=dpi,facecolor=dark_bg)
        return output.getvalue()
    finally:
        fig.clear()
