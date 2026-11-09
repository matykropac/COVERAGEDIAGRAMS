"""OpenAIP CTR/TMA vector overlays: bounded lookup, validation and portable GeoJSON.

OpenAIP community data are a reference overlay, NOT an official AIP or a
live NOTAM service. Geometry stays independent of the radar terrain model.
"""
import json
import math
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely.geometry import shape, mapping, Point
from shapely.ops import transform
from pyproj import Geod

API_URL = "https://api.core.openaip.net/api/airspaces"
KINDS = {4: "CTR", 7: "TMA"}
CLASS_NAMES = {0:"A",1:"B",2:"C",3:"D",4:"E",5:"F",6:"G",8:"UNCLASSIFIED"}
GEOD = Geod(ellps="WGS84")
MAX_ITEMS = 200
MAX_COORDINATES = 10000
MAX_RESPONSE_BYTES = 6_000_000


def _valid_site(lat, lon):
    lat, lon = float(lat), float(lon)
    if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
        raise ValueError("Neplatné souřadnice letiště.")
    return lat, lon


def _limit_text(value, length=150):
    return str(value or "").strip()[:length]


def _datum_limit(value):
    """Keep source units and reference text; never silently turn AGL into AMSL."""
    if not isinstance(value, dict):
        return {"text":"N/A","amsl_ft":None}
    val=value.get("value")
    unit=value.get("unit")
    ref=value.get("referenceDatum")
    try:
        v=float(val)
    except (ValueError, TypeError):
        v=None
    if v is None or not math.isfinite(v) or abs(v)>1000000:
        return {"text":"N/A","amsl_ft":None}
    unit_name = "m" if unit==0 else "ft" if unit==1 else "unit?"
    ref_name = {0:"GND",1:"MSL",2:"STD"}.get(ref,str(ref) if ref is not None else "?")
    ft=v/0.3048 if unit==0 else v if unit==1 else None
    # Do not claim reliable conversion unless source datum explicitly means MSL.
    amsl_ft=ft if ref_name=="MSL" else None
    return {"text":f"{v:g} {unit_name} {ref_name}","amsl_ft":amsl_ft}


def _geometry_valid(geometry):
    if not isinstance(geometry,dict) or geometry.get("type") not in ("Polygon","MultiPolygon"):
        raise ValueError("Vzdušný prostor musí být Polygon nebo MultiPolygon.")
    data=geometry.get("coordinates")
    if not isinstance(data,(list,tuple)):
        raise ValueError("Geometrie bez souřadnic.")
    def iter_coordinates(value):
        if isinstance(value, (tuple,list)) and len(value)>=2 and all(isinstance(x,(int,float)) for x in value[:2]):
            yield value
        elif isinstance(value,(list,tuple)):
            for item in value:
                yield from iter_coordinates(item)
        else:
            raise ValueError("Neplatná struktura polygonu.")
    points=list(iter_coordinates(data))
    if len(points)<4 or len(points)>MAX_COORDINATES:
        raise ValueError("Nepovolená velikost polygonu.")
    if any(not all(math.isfinite(float(x)) for x in p[:2]) or not (-180<=p[0]<=180 and -90<=p[1]<=90) for p in points):
        raise ValueError("Neplatné souřadnice polygonu.")
    geom=shape(geometry)
    if geom.is_empty or not geom.is_valid or geom.area<=0:
        raise ValueError("Neplatná topologie polygonu.")
    return geom


def _http_get(url, api_key):
    req=Request(url,headers={"x-openaip-api-key":api_key,"Accept":"application/json",
                             "User-Agent":"COVERAGEDIAGRAMS/1.0"})
    with urlopen(req,timeout=18) as response:
        content=response.read(MAX_RESPONSE_BYTES+1)
    if len(content)>MAX_RESPONSE_BYTES:
        raise ValueError("OpenAIP vrátil příliš mnoho dat.")
    return json.loads(content.decode("utf-8"))


def fetch_airspaces(lat,lon,radius_km,api_key,fetch=None):
    """Read up to 4 pages around airport; limit retained zones by geometry."""
    lat,lon=_valid_site(lat,lon)
    radius=float(radius_km)
    if not 1<=radius<=200:
        raise ValueError("Poloměr vyhledávání musí být 1–200 km.")
    if not isinstance(api_key,str) or not api_key.strip():
        raise ValueError("Chybí OPENAIP_API_KEY.")
    get=fetch or (lambda url:_http_get(url,api_key.strip()))
    # API uses pos='lat,lon' and dist in meters, not kilometres.
    items=[]
    for page in range(1,5):
        query=urlencode({"pos":f"{lat:.6f},{lon:.6f}","dist":int(radius*1000),
                         "limit":100,"page":page})
        payload=get(API_URL+"?"+query)
        if not isinstance(payload,dict) or not isinstance(payload.get("items"),list):
            raise ValueError("Neočekávaná odpověď OpenAIP.")
        items.extend(payload["items"])
        total_pages=payload.get("totalPages",page)
        if not isinstance(total_pages,int) or total_pages<=page:
            break
    else:
        if total_pages>4:
            raise ValueError("Zdroj obsahuje příliš mnoho prostorů; zmenši poloměr.")
    from pyproj import CRS, Transformer
    crs=CRS.from_proj4(f"+proj=aeqd +lat_0={lat:.8f} +lon_0={lon:.8f} +datum=WGS84 +units=m")
    project=Transformer.from_crs("EPSG:4326",crs,always_xy=True).transform
    selected=[]
    for item in items:
        if not isinstance(item,dict) or item.get("type") not in KINDS:
            continue
        try:
            geom=_geometry_valid(item.get("geometry"))
        except (ValueError, TypeError):
            continue
        # OpenAIP radius lookup might return features by centroid; recheck
        # actual boundary distance geodesically using a local equidistant CRS.
        projected=transform(project,geom)
        if projected.distance(Point(0,0))>radius*1000:
            continue
        lower=_datum_limit(item.get("lowerLimit"))
        upper=_datum_limit(item.get("upperLimit"))
        selected.append({
            "id":_limit_text(item.get("_id") or item.get("id") or item.get("name"),80),
            "name":_limit_text(item.get("name")),
            "kind":KINDS[item["type"]],
            "class":CLASS_NAMES.get(item.get("icaoClass"),"?"),
            "lower":lower,
            "upper":upper,
            "geometry":json.loads(json.dumps(mapping(geom))),
            "source":"OpenAIP",
            "verified_aip":False,"hidden":False,
        })
        if len(selected)>=MAX_ITEMS:
            break
    ids=set()
    result=[]
    for item in selected:
        if item["id"] in ids:
            continue
        ids.add(item["id"])
        result.append(item)
    return result


def validate_saved_airspaces(entries):
    if not isinstance(entries,list) or len(entries)>MAX_ITEMS:
        raise ValueError("Neplatný počet vzdušných prostorů v projektu.")
    output=[]
    for item in entries:
        if not isinstance(item,dict) or item.get("kind") not in ("CTR","TMA"):
            raise ValueError("Nepodporovaný typ vzdušného prostoru.")
        geom=_geometry_valid(item.get("geometry"))
        if item.get("source") not in ("OpenAIP","GeoJSON import"):
            raise ValueError("Neznámý zdroj vzdušného prostoru.")
        clone=dict(item)
        clone["geometry"]=json.loads(json.dumps(mapping(geom)))
        clone["name"]=_limit_text(item.get("name"))
        clone["id"]=_limit_text(item.get("id"),80)
        clone["class"]=_limit_text(item.get("class"),20)
        clone["hidden"]=bool(item.get("hidden",False))
        for side in ("lower","upper"):
            limit=item.get(side)
            if not isinstance(limit,dict):
                raise ValueError("Chybí vertikální meze prostoru.")
            n=limit.get("amsl_ft")
            if n is not None and (not isinstance(n,(float,int)) or not math.isfinite(n)):
                raise ValueError("Neplatná vertikální mez prostoru.")
            clone[side]={"text":_limit_text(limit.get("text"),80),"amsl_ft":n}
        output.append(clone)
    return output


def visible_airspaces(entries,show_ctr=True,show_tma=True,altitude_ft=None):
    out=[]
    for item in entries:
        if item.get("hidden",False):
            continue
        if item["kind"]=="CTR" and not show_ctr or item["kind"]=="TMA" and not show_tma:
            continue
        if altitude_ft is not None:
            lo=item["lower"].get("amsl_ft")
            hi=item["upper"].get("amsl_ft")
            # Unknown vertical reference stays visible; never silently hide it.
            if lo is not None and altitude_ft<lo or hi is not None and altitude_ft>hi:
                continue
        out.append(item)
    return out


def as_geojson(entries):
    return {"type":"FeatureCollection","features":[{
        "type":"Feature","geometry":item["geometry"],
        "properties":{key:item[key] for key in ("id","name","kind","class","lower","upper","source","verified_aip","hidden")}
    } for item in validate_saved_airspaces(entries)]}


def import_geojson(blob):
    if len(blob)>MAX_RESPONSE_BYTES:
        raise ValueError("GeoJSON je příliš velký.")
    data=json.loads(blob.decode("utf-8-sig"))
    if not isinstance(data,dict) or data.get("type")!="FeatureCollection":
        raise ValueError("Očekávám GeoJSON FeatureCollection.")
    if len(data.get("features",[]))>MAX_ITEMS:
        raise ValueError("Příliš mnoho polygonů.")
    zones=[]
    for i,feature in enumerate(data["features"]):
        props=feature.get("properties") or {}
        kind=str(props.get("kind") or props.get("type") or "").upper()
        if kind not in ("CTR","TMA"):
            continue
        zones.append({
            "id":_limit_text(props.get("id") or str(i),80),
            "name":_limit_text(props.get("name") or f"{kind} {i}"),
            "kind":kind,"class":_limit_text(props.get("class") or "?"),
            "lower":props.get("lower") if isinstance(props.get("lower"),dict) else {"text":"N/A","amsl_ft":None},
            "upper":props.get("upper") if isinstance(props.get("upper"),dict) else {"text":"N/A","amsl_ft":None},
            "geometry":feature.get("geometry"),"source":"GeoJSON import",
            "verified_aip":False,"hidden":False})
    return validate_saved_airspaces(zones)
