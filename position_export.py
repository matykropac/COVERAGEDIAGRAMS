"""Standalone editable-position layers export, independent of radar computation.

Outputs WGS84 KML/KMZ and GeoJSON usable in QGIS.  No imagery or raster
tiles are embedded.  Units/reference and source uncertainty remain explicit.
"""
from io import BytesIO
import json
import math
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from obstacles import obstacle_polygon

KML="http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML)
MAX_EXPORT_FEATURES=60000


def _tag(parent, name, value=None):
    node=ET.SubElement(parent,"{"+KML+"}"+name)
    if value is not None:
        node.text=str(value)
    return node


def _check_point(lat,lon):
    lat,lon=float(lat),float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180):
        raise ValueError("Neplatné souřadnice geodat.")
    return [lon,lat]


def _line(points):
    return {"type":"LineString","coordinates":[_check_point(*point) for point in points]}


def _polygon(points):
    ring=[_check_point(*point) for point in points]
    if len(ring)<3:
        raise ValueError("Polygon má méně než 3 vrcholy.")
    if ring[0]!=ring[-1]:
        ring.append(ring[0])
    return {"type":"Polygon","coordinates":[ring]}


def _feature(group,name,geometry,**properties):
    return {"type":"Feature","geometry":geometry,"properties":{
        "layer":group,"name":str(name)[:160],**properties}}


def _airport_features(runways):
    for runway in runways:
        ends=runway["ends"]
        if len(ends)!=2:
            continue
        airport=runway.get("label","RWY")
        points=[[float(p["lat"]),float(p["lon"])] for p in ends]
        yield _feature("RUNWAY_CENTERLINE",airport,_line(points),
                       heading_true_deg=runway.get("heading_deg_true"),
                       length_m=runway.get("length_m"),
                       width_m=runway.get("width_m"),
                       source=runway.get("source","OurAirports"),
                       verified_aip=bool(runway.get("verified_aip",False)))
        # Runway approach extension is a distinct line in the map and must
        # remain independently selectable in the KML folder tree.
        if runway.get("heading_deg_true") is not None:
            heading=float(runway["heading_deg_true"])
            start=_geodesic_point(points[0][0],points[0][1],
                                  heading+180,10*1852)
            end=_geodesic_point(points[1][0],points[1][1],
                                heading,10*1852)
            yield _feature("RUNWAY_EXTENDED_AXIS",
                           airport+" · RWY axis extension 10 NM",
                           _line([start,*points,end]),
                           heading_true_deg=heading,
                           source=runway.get("source","OurAirports"),
                           verified_aip=bool(runway.get("verified_aip",False)))
        for idx,point in enumerate(runway.get("thresholds",[])):
            yield _feature("RUNWAY_THRESHOLDS",f"RWY {ends[idx]['ident']} THR",
                           {"type":"Point","coordinates":_check_point(*point)},
                           rwy=ends[idx]["ident"],
                           source=runway.get("source","OurAirports"),
                           verified_aip=bool(runway.get("verified_aip",False)))
        yield _feature("RUNWAY_MIDPOINT",airport,
                       {"type":"Point","coordinates":_check_point(*runway["midpoint"])},
                       source=runway.get("source","OurAirports"))
    # No inferred runway polygon unless certified pavement edges are supplied.


def _airspace_features(zones):
    for z in zones:
        if z.get("hidden",False):
            continue
        kind=z.get("kind","")
        if kind not in ("CTR","TMA"):
            continue
        yield _feature(kind,z.get("name",kind),z["geometry"],
                       airspace_class=z.get("class","?"),
                       lower=str((z.get("lower") or {}).get("text","N/A")),
                       upper=str((z.get("upper") or {}).get("text","N/A")),
                       source=z.get("source","OpenAIP"),
                       verified_aip=bool(z.get("verified_aip",False)))


def _obstacle_features(obstacles,lat,lon):
    for item in obstacles:
        coords=obstacle_polygon(item,lat,lon)
        yield _feature("OBSTACLES",item.get("name","Překážka"),_polygon(coords),
                       height_agl_m=float(item["height_m"]),
                       source=str(item.get("source","manual")),
                       catalog_id=str(item.get("catalog_id","")))


def _environment_features(items):
    for item in items:
        coords=item.get("coordinates") or []
        if len(coords)<3:
            continue
        category=str(item.get("category") or item.get("kind") or "Building")
        if category not in ("Building","Forest","Tower","Wind"):
            category="Building"
        h=item.get("height_m")
        height=float(h) if h is not None else None
        if height is not None and not math.isfinite(height):
            height=None
        yield _feature("GEODATA_"+category.upper(),
                       item.get("name","Objekt"),_polygon(coords),
                       height_agl_m=height,
                       height_quality=str(item.get("height_quality","unknown")),
                       source=str(item.get("source","OpenStreetMap")),
                       enabled_as_obstacle=bool(item.get("enabled",False)))


def _geodesic_point(lat,lon,bearing,distance_m):
    from pyproj import Geod
    lo,la,_=Geod(ellps="WGS84").fwd(
        float(lon),float(lat),float(bearing),float(distance_m))
    return [float(la),float(lo)]


def par_helper_features(*,site_lat,site_lon,bearing_deg,range_km=40.,
                        runway=None,runways=None,runway_end=0,include_range=True):
    """Visible PAR engineering guides in WGS84; also exported unchanged to KML.

    Runway direction is indicative OurAirports TRUE heading, not verified AIP.
    The local geodesic at the radar is parallel in bearing to the reference RWY;
    it is not claimed to be the exact offset of the finite RWY geodesic.
    """
    lat=float(site_lat);lon=float(site_lon);az=float(bearing_deg)%360
    distance=float(range_km)*1000
    _check_point(lat,lon)
    if not (math.isfinite(distance) and 100<=distance<=500000):
        raise ValueError("Neplatný dosah pro pomocné geometrie PAR.")
    site=[lat,lon]
    features=[_feature("PAR_REFERENCE","PAR · stanoviště radaru",
                       {"type":"Point","coordinates":_check_point(lat,lon)},
                       bearing_true_deg=az)]
    def ray(name,bearing,layer="PAR_SCAN_GEOMETRY",color=None):
        end=_geodesic_point(lat,lon,bearing,distance)
        features.append(_feature(layer,name,_line([site,end]),
                                 bearing_true_deg=round(bearing%360,6),
                                 range_km=distance/1000))
    # Two mirrored 30° sectors, forward and reverse along the same line.
    # The line export must match the two interactive Leaflet wedges.
    for reverse,part in ((0,"PŘEDNÍ"),(180,"ZADNÍ")):
        direction=(az+reverse)%360
        ray(f"PAR · osa {part}",direction)
        ray(f"PAR · hranice −15° {part}",direction-15)
        ray(f"PAR · hranice +15° {part}",direction+15)
        arc=[_geodesic_point(lat,lon,direction+v*.5,distance)
             for v in range(-30,31)]
        features.append(_feature("PAR_SCAN_GEOMETRY",
                                 f"PAR · vnější oblouk ±15° {part}",
                                 _line(arc),range_km=distance/1000))
    references=list(runways) if runways else ([runway] if runway else [])
    for reference in references:
        # Every loaded runway defines two orthogonal reference axes through
        # the radar, independently of which runway is selected in the editor.
        heading=float(reference["heading_deg_true"])
        if not math.isfinite(heading):
            continue
        if runway is reference and int(runway_end)==1:
            heading=(heading+180)%360
        label=str(reference.get("label",""))
        attribution={
            "bearing_true_deg":round(heading%360,6),
            "source":str(reference.get("source","OurAirports")),
            "verified_aip":bool(reference.get("verified_aip",False)),
        }
        parallel=[_geodesic_point(lat,lon,heading+180,distance),
                  site,_geodesic_point(lat,lon,heading,distance)]
        features.append(_feature("PAR_RUNWAY_REFERENCE",
             "PAR · rovnoběžka RWY "+label,_line(parallel),**attribution))
        perpendicular=[
            _geodesic_point(lat,lon,heading-90,distance),site,
            _geodesic_point(lat,lon,heading+90,distance)]
        features.append(_feature("PAR_RUNWAY_REFERENCE",
             "PAR · kolmice RWY "+label,_line(perpendicular),
             **dict(attribution,bearing_true_deg=round((heading+90)%360,6))))
    if include_range:
        for nm in range(20,261,20):
            # Existing RANGE circles used by the application, sampled 2°.
            ring=[_geodesic_point(lat,lon,degree,nm*1852)
                  for degree in range(0,361,2)]
            features.append(_feature("RADAR_RANGE_RINGS",f"RANGE · {nm} NM",
                                     _line(ring),radius_nm=nm))
    return features


def make_layer_features(*,runways=(),airspaces=(),obstacles=(),environment=(),
                        site_lat=None,site_lon=None,
                        include_runways=True,include_airspaces=True,
                        include_obstacles=True,include_environment=True,
                        par=None,include_par_helpers=True):
    """Always returns only selected layers; never accesses a radar result."""
    features=[]
    if include_runways:
        features.extend(_airport_features(runways))
    if include_airspaces:
        features.extend(_airspace_features(airspaces))
    if include_obstacles:
        if obstacles and (site_lat is None or site_lon is None):
            raise ValueError("Chybí referenční poloha pro překážky.")
        features.extend(_obstacle_features(obstacles,site_lat,site_lon))
    if include_environment:
        features.extend(_environment_features(environment))
    if include_par_helpers and par and par.get("enabled"):
        features.extend(par_helper_features(
            site_lat=par["lat"],site_lon=par["lon"],
            bearing_deg=par["bearing"],range_km=par.get("range_km",40),
            runway=par.get("runway"),runways=par.get("runways"),
            runway_end=par.get("runway_end",0)))
    if len(features)>MAX_EXPORT_FEATURES:
        raise ValueError(f"Export překročil limit {MAX_EXPORT_FEATURES} prvků. Omez vrstvy.")
    return features


def geojson_bytes(features):
    return json.dumps({"type":"FeatureCollection","features":features},
                      ensure_ascii=False,allow_nan=False).encode("utf-8")


def _coords(positions):
    return " ".join(f"{float(p[0]):.9f},{float(p[1]):.9f},0" for p in positions)


def _kml_geometry(parent,geometry):
    kind=geometry["type"]
    coords=geometry["coordinates"]
    if kind=="Point":
        _tag(_tag(parent,"Point"),"coordinates",_coords([coords]))
    elif kind=="LineString":
        _tag(_tag(parent,"LineString"),"coordinates",_coords(coords))
    elif kind=="Polygon":
        poly=_tag(parent,"Polygon")
        for i,ring in enumerate(coords):
            boundary=_tag(poly,"outerBoundaryIs" if i==0 else "innerBoundaryIs")
            _tag(_tag(boundary,"LinearRing"),"coordinates",_coords(ring))
    elif kind=="MultiPolygon":
        group=_tag(parent,"MultiGeometry")
        for poly_coords in coords:
            _kml_geometry(group,{"type":"Polygon","coordinates":poly_coords})
    else:
        raise ValueError("Nepodporovaná geometrie "+str(kind))


def kml_bytes(features):
    root=ET.Element("{"+KML+"}kml")
    doc=_tag(root,"Document")
    _tag(doc,"name","COVERAGEDIAGRAMS · Map layers / QGIS")
    _tag(doc,"description",
         "WGS84 reference layers; OSM/OurAirports/OpenAIP are not certified AIP or obstacle surveys.")
    folders={}
    for feature in features:
        props=feature["properties"]
        layer=props["layer"]
        if layer not in folders:
            folders[layer]=_tag(doc,"Folder")
            _tag(folders[layer],"name",layer)
        mark=_tag(folders[layer],"Placemark")
        _tag(mark,"name",props.get("name",""))
        ext=_tag(mark,"ExtendedData")
        for name,value in props.items():
            data=_tag(ext,"Data")
            data.set("name",name)
            _tag(data,"value","" if value is None else str(value))
        _kml_geometry(mark,feature["geometry"])
    return ET.tostring(root,encoding="utf-8",xml_declaration=True)


def kmz_bytes(features):
    data=BytesIO()
    with ZipFile(data,"w",compression=ZIP_DEFLATED,compresslevel=6) as z:
        z.writestr("doc.kml",kml_bytes(features))
    return data.getvalue()
