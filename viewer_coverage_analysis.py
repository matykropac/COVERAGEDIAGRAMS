"""Exact geodesic analysis of unmodified WGS84 VIEWER polygons.

All outputs are derived layers; original features and radar arrays are never edited.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from shapely.geometry import shape, mapping, Polygon, MultiPolygon, GeometryCollection
from shapely.ops import unary_union, transform
from shapely.validation import make_valid
from pyproj import Geod, Transformer

GEOD=Geod(ellps="WGS84")
MAX_FEATURES=10000
MAX_COORDINATES=3000000


def _polygonal(g):
    """Keep valid polygonal components; discard points/lines from repairs."""
    if g.is_empty:
        return Polygon()
    if not g.is_valid:
        g=make_valid(g)
    if isinstance(g,(Polygon,MultiPolygon)):
        return g
    if isinstance(g,GeometryCollection):
        polygons=[]
        for item in g.geoms:
            if isinstance(item,(Polygon,MultiPolygon)):
                polygons.append(item)
        return unary_union(polygons) if polygons else Polygon()
    return Polygon()


def _coordinate_count(g):
    t=g.get("type")
    if t=="GeometryCollection":
        return sum(_coordinate_count(x) for x in g.get("geometries",[]))
    def walk(value):
        if not isinstance(value,(list,tuple)):return 0
        if len(value)>=2 and all(isinstance(x,(float,int)) for x in value[:2]):return 1
        return sum(walk(x) for x in value)
    return walk(g.get("coordinates",[]))


def coverage_union(features):
    """Merge a single layer into one topology-correct coverage mask."""
    if len(features)>MAX_FEATURES:
        raise ValueError("Příliš mnoho polygonů; rozděl projekt do menších vrstev.")
    pieces=[];total_points=0
    for feature in features:
        geometry=(feature or {}).get("geometry")
        if not isinstance(geometry,dict):continue
        if geometry.get("type") not in ("Polygon","MultiPolygon","GeometryCollection"):
            continue
        total_points+=_coordinate_count(geometry)
        if total_points>MAX_COORDINATES:
            raise ValueError("Překročen limit souřadnic pro přesnou analýzu.")
        try:
            result=_polygonal(shape(geometry))
        except (ValueError,TypeError) as exc:
            raise ValueError("Neplatná geometrie ve vrstvě.") from exc
        if not result.is_empty:
            pieces.append(result)
    if not pieces:
        raise ValueError("Vrstva neobsahuje polygony radarového krytí.")
    return _polygonal(unary_union(pieces))


def _area_km2(g):
    if g.is_empty:return 0.0
    area,_=GEOD.geometry_area_perimeter(g)
    return abs(area)/1000000.0


def compare_coverage(baseline, candidate, *, baseline_name="BASELINE",
                     candidate_name="CANDIDATE"):
    """Exact planar topology in WGS84, geodesic areas for each result.

    Inputs should be regional, not polygons crossing the antimeridian.
    """
    a=coverage_union(baseline)
    b=coverage_union(candidate)
    if a.bounds[2]-a.bounds[0]>180 or b.bounds[2]-b.bounds[0]>180:
        raise ValueError("Analýza polygonů přes antimeridián není podporována.")
    common=_polygonal(a.intersection(b))
    gained=_polygonal(b.difference(a))
    lost=_polygonal(a.difference(b))
    results={"baseline":a,"candidate":b,"common":common,
             "gained":gained,"lost":lost}
    metrics={key:round(_area_km2(value),5) for key,value in results.items()}
    metrics["gain_percent_of_baseline"]=round(
        100*metrics["gained"]/metrics["baseline"],3) if metrics["baseline"] else None
    metrics["loss_percent_of_baseline"]=round(
        100*metrics["lost"]/metrics["baseline"],3) if metrics["baseline"] else None
    palette={"common":"#268ad5","gained":"#2abd77","lost":"#ee6371"}
    derived=[]
    for key in ("common","gained","lost"):
        geometry=results[key]
        if not geometry.is_empty:
            derived.append({"type":"Feature","properties":{
                "name":key.upper(),"comparison":True,
                "baseline":baseline_name,"candidate":candidate_name,
                "area_km2":metrics[key],"source":"VIEWER derived, WGS84"},
                "geometry":mapping(geometry)})
    return {"metrics":metrics,"features":derived,
            "style_colors":palette,"method":"GEOS WGS84 overlay + ellipsoidal area"}


def coverage_stats(features, *, radar_lat=None, radar_lon=None,
                   sectors=12, range_nm=None):
    """Topologically de-duplicated area and optional AZ sector breakdown.

    Sector and range statistics are clipped on a local azimuthal equidistant
    projection. Sector values therefore use approximate geodesic boundaries;
    final areas are ellipsoidal WGS84.
    """
    mask=coverage_union(features)
    result={"area_km2":round(_area_km2(mask),5),
            "polygon_count":len(features),"sectors":[]}
    if radar_lat is None or radar_lon is None:
        return result
    if not (-90<radar_lat<90 and -180<=radar_lon<=180):
        raise ValueError("Neplatné souřadnice radaru.")
    if not 1<=sectors<=72 or 360%sectors:
        raise ValueError("Počet sektorů musí dělit 360.")
    local=f"+proj=aeqd +lat_0={radar_lat} +lon_0={radar_lon} +datum=WGS84 +units=m"
    fw=Transformer.from_crs("EPSG:4326",local,always_xy=True).transform
    back=Transformer.from_crs(local,"EPSG:4326",always_xy=True).transform
    local_mask=transform(fw,mask)
    radius=(float(range_nm)*1852 if range_nm is not None else
            max(1000.,max(math.hypot(x,y) for x,y in (
                (local_mask.bounds[0],local_mask.bounds[1]),
                (local_mask.bounds[0],local_mask.bounds[3]),
                (local_mask.bounds[2],local_mask.bounds[1]),
                (local_mask.bounds[2],local_mask.bounds[3])))))
    if not 0<radius<=600000:
        raise ValueError("RANGE pro sektorovou analýzu musí být 0–324 NM.")
    step=360/sectors
    for index in range(sectors):
        start=index*step
        angles=[start+step*i/max(4,int(step/2)) for i in range(max(4,int(step/2))+1)]
        ring=[(0.,0.)]+[(radius*math.sin(math.radians(az)),
                         radius*math.cos(math.radians(az))) for az in angles]+[(0.,0.)]
        wedge=Polygon(ring)
        intersection=_polygonal(local_mask.intersection(wedge))
        area=_area_km2(transform(back,intersection))
        sector_area=_area_km2(transform(back,wedge))
        result["sectors"].append({
            "az_from":start,"az_to":start+step,
            "covered_km2":round(area,5),
            "sector_km2":round(sector_area,5),
            "percent":round(100*area/sector_area,3) if sector_area else None})
    return result
