"""Vector-first PDF map compositor for COVERAGEDIAGRAMS customer atlases.

Source WGS84 GeoJSON remains untouched. Output is a cartographic drawing in
Web Mercator coordinates, not an RF validation or an offline basemap copy.
"""
from __future__ import annotations

import math
from pyproj import Transformer
from reportlab.lib.colors import HexColor, Color
from reportlab.pdfgen.canvas import Canvas


def _xyiter(geometry):
    t=geometry.get("type")
    coords=geometry.get("coordinates",[])
    if t=="Point":yield coords
    elif t in ("MultiPoint","LineString"):
        yield from coords
    elif t in ("MultiLineString","Polygon"):
        for part in coords:
            yield from part
    elif t=="MultiPolygon":
        for poly in coords:
            for ring in poly:
                yield from ring
    elif t=="GeometryCollection":
        for child in geometry.get("geometries",[]):
            yield from _xyiter(child)


def _feature_geometry(geometry):
    t=geometry.get("type")
    coords=geometry.get("coordinates",[])
    if t=="Polygon":yield "polygon",coords
    elif t=="MultiPolygon":
        for polygon in coords:yield "polygon",polygon
    elif t=="LineString":yield "line",coords
    elif t=="MultiLineString":
        for line in coords:yield "line",line
    elif t=="Point":yield "point",[coords]
    elif t=="MultiPoint":
        for point in coords:yield "point",[point]
    elif t=="GeometryCollection":
        for child in geometry.get("geometries",[]):
            yield from _feature_geometry(child)


def draw_vector_map(c: Canvas, layers, styles, rect, *, dark=False,
                    north=True, scale=True, graticule=True):
    """Draw all selected input geometries directly as PDF vector paths.

    rect = (x, y, width, height) in PDF points. Returns the projected extent.
    """
    x0,y0,width,height=rect
    if width<=0 or height<=0:raise ValueError("Invalid cartographic frame.")
    selected=[(name,features,styles[name]) for name,features in layers.items()
              if styles.get(name,{}).get("show",False)]
    if not selected:raise ValueError("Není vybrána žádná viditelná vrstva.")
    projection=Transformer.from_crs("EPSG:4326","EPSG:3857",always_xy=True)
    bounds=[math.inf,math.inf,-math.inf,-math.inf]
    coord_count=0
    for _,features,_ in selected:
        if len(features)>50000:raise ValueError("Too many features for PDF.")
        for f in features:
            g=(f or {}).get("geometry")
            if not isinstance(g,dict):continue
            for p in _xyiter(g):
                if not isinstance(p,(list,tuple)) or len(p)<2:continue
                lon,lat=p[:2]
                if not (isinstance(lon,(int,float)) and isinstance(lat,(int,float)) and
                        math.isfinite(lon) and math.isfinite(lat) and -180<=lon<=180 and
                        -85<=lat<=85):continue
                coord_count+=1
                if coord_count>1500000:raise ValueError("PDF vertex limit exceeded.")
                px,py=projection.transform(lon,lat)
                bounds=[min(bounds[0],px),min(bounds[1],py),
                        max(bounds[2],px),max(bounds[3],py)]
    if not math.isfinite(bounds[0]):raise ValueError("Viditelné vrstvy neobsahují mapovou geometrii.")
    minx,miny,maxx,maxy=bounds
    dx=max(maxx-minx,1000.)
    dy=max(maxy-miny,1000.)
    pad=max(dx,dy)*.065
    minx-=pad;maxx+=pad;miny-=pad;maxy+=pad
    dx=maxx-minx;dy=maxy-miny
    factor=min(width/dx,height/dy)
    mx=x0+(width-dx*factor)/2;my=y0+(height-dy*factor)/2
    def pdfpoint(lon,lat):
        xx,yy=projection.transform(lon,lat)
        return mx+(xx-minx)*factor,my+(yy-miny)*factor
    c.saveState()
    c.setFillColor(HexColor("#081c30") if dark else HexColor("#fbfdff"))
    c.rect(x0,y0,width,height,fill=1,stroke=0)
    c.setStrokeColor(HexColor("#375d79") if dark else HexColor("#b3c8d8"))
    c.setLineWidth(.65);c.rect(x0,y0,width,height,fill=0,stroke=1)
    p=c.beginPath();p.rect(x0,y0,width,height);c.clipPath(p,stroke=0,fill=0)
    if graticule:
        left,bottom=projection.transform(-180,-85)
        # Lines in metric projected space keep the grid calm at any zoom.
        step=10**math.floor(math.log10(max(dx,dy)/5))
        if max(dx,dy)/step>12:step*=2
        c.setStrokeColor(HexColor("#45647d") if dark else HexColor("#d1dde6"))
        c.setLineWidth(.35)
        for xx in range(math.ceil(minx/step),math.floor(maxx/step)+1):
            x=mx+(xx*step-minx)*factor
            c.line(x,y0,x,y0+height)
        for yy in range(math.ceil(miny/step),math.floor(maxy/step)+1):
            y=my+(yy*step-miny)*factor
            c.line(x0,y,x0+width,y)
    for _,features,style in selected:
        try:color=HexColor(style.get("color","#58badc"))
        except (ValueError,TypeError):color=HexColor("#58badc")
        stroke=max(.2,min(8,float(style.get("width",1.5))))
        opacity=max(0,min(1,float(style.get("opacity",.35))))
        c.setStrokeColor(color);c.setFillColor(color);c.setLineWidth(stroke)
        c.setFillAlpha(opacity);c.setStrokeAlpha(1)
        for feature in features:
            g=(feature or {}).get("geometry")
            if not isinstance(g,dict):continue
            for kind,segments in _feature_geometry(g):
                if kind=="polygon":
                    path=c.beginPath()
                    for ring in segments:
                        coords=[]
                        for p in ring:
                            if len(p)>=2 and math.isfinite(p[0]) and math.isfinite(p[1]):
                                coords.append(pdfpoint(p[0],p[1]))
                        if len(coords)<3:continue
                        path.moveTo(*coords[0])
                        for a in coords[1:]:path.lineTo(*a)
                        path.close()
                    c.drawPath(path,stroke=1,fill=1,fillMode=0)
                elif kind=="line":
                    coords=[pdfpoint(p[0],p[1]) for p in segments
                            if len(p)>=2 and math.isfinite(p[0]) and math.isfinite(p[1])]
                    if len(coords)>1:
                        path=c.beginPath();path.moveTo(*coords[0])
                        for point in coords[1:]:path.lineTo(*point)
                        c.drawPath(path,stroke=1,fill=0)
                elif kind=="point":
                    for point in segments:
                        if len(point)<2:continue
                        px,py=pdfpoint(point[0],point[1]);c.circle(px,py,2.3,stroke=1,fill=1)
    c.restoreState()
    if north:
        c.saveState()
        c.setFillColor(HexColor("#e2f1ff") if dark else HexColor("#15334b"))
        c.setFont("Helvetica-Bold",14)
        c.drawCentredString(x0+width-22,y0+height-24,"N")
        c.setLineWidth(2);c.line(x0+width-22,y0+height-52,x0+width-22,y0+height-33)
        p=c.beginPath();p.moveTo(x0+width-22,y0+height-30)
        p.lineTo(x0+width-27,y0+height-40);p.lineTo(x0+width-17,y0+height-40);p.close()
        c.drawPath(p,fill=1,stroke=0);c.restoreState()
    if scale:
        # Meter lengths are EPSG:3857 projected distances, not ground truth.
        scale_m=10**math.floor(math.log10(max(1,dx/5)))
        if dx/scale_m>12:scale_m*=2
        length_pt=scale_m*factor
        if length_pt>width*.65:scale_m/=2;length_pt=scale_m*factor
        sx=x0+22;sy=y0+22
        c.saveState()
        c.setStrokeColor(HexColor("#c4edff") if dark else HexColor("#142e43"))
        c.setLineWidth(2.1);c.line(sx,sy,sx+length_pt,sy)
        c.line(sx,sy-4,sx,sy+4);c.line(sx+length_pt,sy-4,sx+length_pt,sy+4)
        c.setFillColor(HexColor("#c4edff") if dark else HexColor("#142e43"))
        c.setFont("Helvetica",8)
        c.drawString(sx,sy+7,"0")
        c.drawRightString(sx+length_pt,sy+7,f"{scale_m/1000:g} km (Mercator grid)")
        c.restoreState()
    return {"projection":"EPSG:3857","bounds_projected":[minx,miny,maxx,maxy],
            "vertices":coord_count,"layers":len(selected)}
