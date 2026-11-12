"""Optional OSM environment layers with bounded queries, explicit uncertainty and export."""
import csv
import io
import json
import math
import re
import urllib.parse
import urllib.request
from html import escape
from xml.etree import ElementTree as ET

import folium
import streamlit as st
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
MAX_ENVIRONMENT_ITEMS = 50000
MAX_MAP_POLYGONS = 6000

COLORS = {"Building": "#e3a64c", "Forest": "#48ae78", "Tower": "#d778ed"}
LABELS = {"Building": "Budovy", "Forest": "Lesy / porost", "Tower": "Stožáry a věže"}
SOURCES = (
    "© OpenStreetMap contributors (ODbL 1.0). "
    "Výšky jsou pouze hodnoty z atributů OSM, nikoli geodeticky ověřená měření."
)

def numeric_height(value):
    """Read simple OSM metres/feet safely; never treat unknown height as zero."""
    if value is None:
        return None
    s = str(value).strip().lower().replace(",", ".")
    if not s:
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(m|metres?|meters?|ft|feet|')?", s)
    if not match:
        return None
    n = float(match.group(1))
    if match.group(2) in ("ft", "feet", "'"):
        n *= .3048
    return round(n, 2) if 0 < n <= 1000 else None

def _kind(tags):
    if "building" in tags:
        return "Building"
    if tags.get("natural") == "wood" or tags.get("landuse") == "forest":
        return "Forest"
    if tags.get("man_made") in ("tower", "mast", "chimney"):
        return "Tower"
    return None

def _height(tags):
    explicit = numeric_height(tags.get("height_m") or tags.get("height") or tags.get("building:height"))
    if explicit is not None:
        return explicit, "OSM height"
    if "building" in tags:
        levels = numeric_height(tags.get("building:levels"))
        if levels is not None:
            return None, f"{levels:g} floors (height unverified)"
    return None, "unknown"

def _ring(coords):
    out = [[float(lat), float(lon)] for lon, lat in coords]
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out

def _feature(kind, coords, tags, source_id):
    if len(coords) < 3 or len(coords) > 1200:
        return None
    height, quality = _height(tags)
    return dict(kind=kind, name=str(tags.get("name") or f"{LABELS[kind]} #{source_id}")[:130],
                coordinates=coords, height_m=height, height_quality=quality,
                source="OpenStreetMap", source_id=str(source_id))


def _overpass_relation_polygons(element):
    """Assemble actual OSM multipolygon outer/inner member ways.

    Overpass 'out geom' gives geometry per relation member, not element.geometry.
    Polygonize disconnected outer ways; preserve holes by splitting polygons
    into hole-free pieces for the existing one-ring obstacle data model.
    """
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize, unary_union, triangulate

    def rings(role):
        segments=[]
        for member in element.get("members") or []:
            if member.get("type")!="way" or member.get("role")!=role:
                continue
            coords=[]
            for pt in member.get("geometry") or []:
                try:
                    lat,lon=float(pt["lat"]),float(pt["lon"])
                except (KeyError,TypeError,ValueError):
                    continue
                if math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180:
                    coords.append((lon,lat))
            if len(coords)>=2:
                segments.append(LineString(coords))
        if not segments:
            return []
        return [poly for poly in polygonize(unary_union(segments)) if poly.is_valid and poly.area>0]

    outers=rings("outer")
    if not outers:
        return []
    inners=rings("inner")
    # MultiPolygon may contain nested independent outers, not only one area.
    area=unary_union(outers)
    if inners:
        area=area.difference(unary_union(inners))
    geometries=list(area.geoms) if hasattr(area,"geoms") else [area]
    output=[]
    for poly in geometries:
        if not isinstance(poly,Polygon) or poly.is_empty or not poly.is_valid:
            continue
        pieces=[poly] if not poly.interiors else [
            tri.intersection(poly) for tri in triangulate(poly)]
        for piece in pieces:
            polys=list(piece.geoms) if hasattr(piece,"geoms") else [piece]
            for p in polys:
                if not isinstance(p,Polygon) or p.is_empty or p.area<=0 or p.interiors:
                    continue
                points=[[float(lat),float(lon)] for lon,lat in list(p.exterior.coords)[:-1]]
                if len(points)>=3:
                    output.append(points)
                if len(output)>=300:
                    return output
    return output


def _simplify_ring(coords, max_vertices=150):
    """Reduce overly detailed OSM footprints without falsifying their extent."""
    if len(coords)<=max_vertices:
        return coords
    from shapely.geometry import Polygon
    shape=Polygon([(lon,lat) for lat,lon in coords])
    if not shape.is_valid or shape.is_empty:
        return None
    minimum=max(shape.bounds[2]-shape.bounds[0],shape.bounds[3]-shape.bounds[1])
    # Start sub-metre at midlatitudes, increase until the solver's 150-vertex cap.
    for scale in (1e-6,3e-6,1e-5,3e-5,1e-4,3e-4,1e-3):
        poly=shape.simplify(scale,preserve_topology=True)
        if isinstance(poly,Polygon) and poly.is_valid and not poly.interiors:
            ring=[[float(lat),float(lon)] for lon,lat in list(poly.exterior.coords)[:-1]]
            if 3<=len(ring)<=max_vertices:
                return ring
    return None

OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.maprva.org/api/interpreter",
)

def _overpass_json_with_fallback(payload, *, opener=None, endpoints=None):
    """Retry allowlisted Overpass servers, safely bounding JSON payloads."""
    import urllib.error
    opener = opener or urllib.request.urlopen
    endpoints = endpoints or OVERPASS_ENDPOINTS
    errors = []
    for url in endpoints:
        try:
            request = urllib.request.Request(
                url, data=payload,
                headers={"User-Agent":"COVERAGEDIAGRAMS/2.0 (on-demand geospatial analysis)",
                         "Content-Type":"application/x-www-form-urlencoded",
                         "Accept":"application/json"})
            with opener(request, timeout=40) as response:
                body = response.read(24_000_001)
            if len(body)>24_000_000:
                raise ValueError("příliš velká odpověď (nad 24 MB)")
            parsed = json.loads(body.decode("utf-8"))
            if not isinstance(parsed,dict) or not isinstance(parsed.get("elements"),list):
                raise ValueError("neplatná odpověď Overpass")
            return parsed
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,
                OSError,ValueError,UnicodeError) as exc:
            short = "HTTP "+str(exc.code) if isinstance(exc,urllib.error.HTTPError) else type(exc).__name__
            errors.append(url.split("/")[2]+" ("+short+")")
    raise RuntimeError(
        "Žádný Overpass server neodpověděl: "+"; ".join(errors)
        +". Server může blokovat odchozí spojení; zkus lokální GeoJSON import.")

@st.cache_data(ttl=86400, show_spinner=False, max_entries=32)
def fetch_osm(lat, lon, radius_km):
    """Small on-demand Overpass query. No background scans or bulk tile downloads."""
    radius_km = float(radius_km)
    if radius_km < .5 or radius_km > 10:
        raise ValueError("Online OSM dotaz povoluje pouze 0,5–10 km.")
    meters = int(radius_km * 1000)
    query = ('[out:json][timeout:35];('
             f'way(around:{meters},{lat:.6f},{lon:.6f})["building"];'
             f'relation(around:{meters},{lat:.6f},{lon:.6f})["building"]["type"="multipolygon"];'
             f'way(around:{meters},{lat:.6f},{lon:.6f})["landuse"="forest"];'
             f'relation(around:{meters},{lat:.6f},{lon:.6f})["landuse"="forest"]["type"="multipolygon"];'
             f'way(around:{meters},{lat:.6f},{lon:.6f})["natural"="wood"];'
             f'relation(around:{meters},{lat:.6f},{lon:.6f})["natural"="wood"]["type"="multipolygon"];'
             f'way(around:{meters},{lat:.6f},{lon:.6f})["man_made"~"^(tower|mast|chimney)$"];'
             f'relation(around:{meters},{lat:.6f},{lon:.6f})["man_made"~"^(tower|mast|chimney)$"]["type"="multipolygon"];'
             f'node(around:{meters},{lat:.6f},{lon:.6f})["man_made"~"^(tower|mast|chimney)$"];'
             ');out geom;')
    payload = urllib.parse.urlencode({"data": query}).encode()
    data = _overpass_json_with_fallback(payload)
    items = []
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        kind = _kind(tags)
        geometry = element.get("geometry") or []
        if not kind:
            continue
        if element.get("type") == "relation":
            # Relation's geometry is in its members, never the top-level field.
            for part,coords in enumerate(_overpass_relation_polygons(element)):
                clean=_simplify_ring(coords,1200)
                if clean is None:
                    continue
                item=_feature(kind,clean,tags,f"relation-{element.get('id','unknown')}-{part}")
                if item:
                    items.append(item)
            continue
        if element.get("type") == "node":
            if kind != "Tower" or "lat" not in element or "lon" not in element:
                continue
            plat, plon = float(element["lat"]), float(element["lon"])
            # A point tower needs a footprint for the existing radar model.
            # 10 m visualization square; not surveyed tower dimensions.
            lons, lats, _ = GEOD.fwd([plon]*4, [plat]*4,
                                      [45, 135, 225, 315], [7.071]*4)
            coords = [[float(y), float(x)] for x, y in zip(lons, lats)]
        else:
            if len(geometry) < 3:
                continue
            coords = [[float(p["lat"]), float(p["lon"])] for p in geometry]
        clean=_simplify_ring(coords[:-1] if coords[0] == coords[-1] else coords,1200)
        if clean is None:
            continue
        item = _feature(kind,clean,tags,
                        f"{element.get('type','way')}-{element.get('id','unknown')}")
        if item:
            items.append(item)
    return items[:MAX_ENVIRONMENT_ITEMS]

def import_geojson(raw):
    """Accept GeoJSON Polygon/MultiPolygon with optional height and class properties."""
    data = json.loads(raw)
    features = data.get("features", []) if data.get("type") == "FeatureCollection" else [data]
    items = []
    for i, feature in enumerate(features[:MAX_ENVIRONMENT_ITEMS]):
        geom = feature.get("geometry") or {}
        props = feature.get("properties") or {}
        raw_kind = str(props.get("kind") or props.get("class") or props.get("type") or "Building").lower()
        kind = "Forest" if any(v in raw_kind for v in ("forest", "wood", "tree")) else ("Tower" if any(v in raw_kind for v in ("tower", "mast", "chimney")) else "Building")
        rings = [geom.get("coordinates", [])] if geom.get("type") == "Polygon" else geom.get("coordinates", []) if geom.get("type") == "MultiPolygon" else []
        for part in rings:
            if not part:
                continue
            ring = _ring(part[0])
            if len(ring) < 3:
                continue
            item = _feature(kind, ring, props, f"import-{i}")
            if item:
                item["name"] = str(props.get("name", item["name"]))[:130]
                item["source"] = "Imported GeoJSON"
                items.append(item)
    return items[:MAX_ENVIRONMENT_ITEMS]

def distance_azimuth(item, lat, lon):
    pts = item["coordinates"]
    clat = sum(p[0] for p in pts) / len(pts)
    clon = sum(p[1] for p in pts) / len(pts)
    az, _, dist = GEOD.inv(lon, lat, clon, clat)
    return dist / 1000., az % 360

def selected(items, lat, lon, kinds, min_height, max_distance, include_unknown,
             az_start=0., az_end=360., query=""):
    filtered = []
    query = query.strip().casefold()
    for item in items:
        if item["kind"] not in kinds or (query and query not in str(item.get("name", "")).casefold()):
            continue
        if not item.get("coordinates"):
            continue
        h = item.get("height_m")
        if h is None:
            if not include_unknown:
                continue
        elif h < min_height:
            continue
        dist, az = distance_azimuth(item, lat, lon)
        in_sector = (az_start <= az <= az_end) if az_start <= az_end else (az >= az_start or az <= az_end)
        if dist <= max_distance and in_sector:
            filtered.append({**item, "distance_km": round(dist, 2), "azimuth_deg": round(az, 1)})
    return sorted(filtered, key=lambda item: item["distance_km"])

def layer_group(map_obj, items, name="Environmental objects", visible=True):
    group = folium.FeatureGroup(name=name, show=visible, overlay=True)
    for item in items[:MAX_MAP_POLYGONS]:
        color = COLORS.get(item["kind"], "#dddddd")
        h = item.get("height_m")
        label = escape(str(item.get("name", "")))
        tip = f'{label} · {h:g} m AGL' if h is not None else f'{label} · výška neznámá'
        folium.Polygon(item["coordinates"], color=color, weight=1.3,
                       fill=True, fill_color=color, fill_opacity=.31,
                       tooltip=tip,
                       popup=folium.Popup(tip + "<br>" + escape(item.get("source", "")), max_width=330)).add_to(group)
    group.add_to(map_obj)
    return group

def legend_html(items, additional=""):
    counts = {kind: sum(x["kind"] == kind for x in items) for kind in COLORS}
    details = "".join(
        f'<div style="display:flex;gap:7px;align-items:center;margin:3px 0"><span style="width:12px;height:12px;background:{color};display:inline-block"></span>{LABELS[kind]}: {counts[kind]}</div>'
        for kind, color in COLORS.items())
    return ('<div style="position:absolute;z-index:9999;bottom:26px;left:9px;'
            'background:rgba(7,29,44,.92);color:#e8f6ff;border:1px solid #47677b;'
            'border-radius:7px;padding:10px 13px;font:12px system-ui;pointer-events:none">'
            '<b>MAP LEGEND / LEGENDA</b><hr style="margin:5px 0;border-color:#47677b">'
            + details + '<div style="margin-top:5px;color:#adcad9">'
            + additional + '</div><small>OSM / import · unknown height ≠ 0 m</small></div>')

def add_legend(map_obj, items, additional=""):
    from branca.element import Element
    map_obj.get_root().html.add_child(Element(legend_html(items, additional)))

def geojson_bytes(items):
    feats = []
    for item in items:
        ring = [[lon, lat] for lat, lon in item["coordinates"]]
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])
        feats.append(dict(type="Feature", properties={k: v for k, v in item.items() if k != "coordinates"},
                          geometry=dict(type="Polygon", coordinates=[ring])))
    return json.dumps(dict(type="FeatureCollection", features=feats), ensure_ascii=False, indent=2).encode()

def kml_bytes(items):
    ns = "http://www.opengis.net/kml/2.2"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}kml")
    doc = ET.SubElement(root, f"{{{ns}}}Document")
    ET.SubElement(doc, f"{{{ns}}}name").text = "COVERAGEDIAGRAMS – environmental overlay"
    ET.SubElement(doc, f"{{{ns}}}description").text = SOURCES
    for item in items:
        pm = ET.SubElement(doc, f"{{{ns}}}Placemark")
        ET.SubElement(pm, f"{{{ns}}}name").text = item["name"]
        ET.SubElement(pm, f"{{{ns}}}description").text = f'{item["kind"]}; height AGL: {item["height_m"]}; {item["height_quality"]}; source: {item["source"]}'
        style = ET.SubElement(pm, f"{{{ns}}}Style")
        color = COLORS.get(item["kind"], "#dddddd").lstrip("#")
        # KML colors: aabbggrr; semi-transparent thematic fill.
        kml_color = "88" + color[4:6] + color[2:4] + color[0:2]
        poly_style = ET.SubElement(style, f"{{{ns}}}PolyStyle")
        ET.SubElement(poly_style, f"{{{ns}}}color").text = kml_color
        line_style = ET.SubElement(style, f"{{{ns}}}LineStyle")
        ET.SubElement(line_style, f"{{{ns}}}color").text = "ff" + color[4:6] + color[2:4] + color[0:2]
        poly = ET.SubElement(pm, f"{{{ns}}}Polygon")
        outer = ET.SubElement(poly, f"{{{ns}}}outerBoundaryIs")
        lr = ET.SubElement(outer, f"{{{ns}}}LinearRing")
        coords = [[lon, lat] for lat, lon in item["coordinates"]]
        if coords and coords[0] != coords[-1]:
            coords.append(coords[0])
        ET.SubElement(lr, f"{{{ns}}}coordinates").text = " ".join(f"{lon:.7f},{lat:.7f},0" for lon, lat in coords)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

def csv_bytes(items):
    columns = ["name", "kind", "height_m", "height_quality", "distance_km", "azimuth_deg", "source", "source_id"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(items)
    return out.getvalue().encode("utf-8-sig")

def controls(lat, lon, prefix):
    """Shared filters, loaded only on deliberate request; used on both map tabs."""
    st.markdown("**Environment / Výškové objekty**")
    radius = st.slider("Načíst OSM do [km]", .5, 10., 3., .5, key=prefix+"_radius")
    if st.button("Načíst budovy / lesy / věže (OSM)", key=prefix+"_fetch", use_container_width=True):
        try:
            with st.spinner("Načítám OSM; rozsáhlá města mohou překročit limit služby…"):
                st.session_state["environment_items"] = fetch_osm(round(lat, 5), round(lon, 5), radius)
                st.session_state["environment_site"] = (round(lat, 5), round(lon, 5))
            st.success(f'Načteno {len(st.session_state["environment_items"])} polygonů')
        except Exception as exc:
            st.warning("OSM nyní nelze načíst: " + str(exc)[:180])
    if st.button("Načíst Microsoft Building Footprints (lokálně, beta)",
                 key=prefix+"_microsoft", use_container_width=True,
                 help="Otevřená databáze Microsoft 2026. Max. 3 zdrojové dlaždice a 50 000 budov; "
                      "ve velkých městech může služba vrátit limit nebo chybu."):
        try:
            from microsoft_buildings import fetch_microsoft
            with st.spinner("Čtu geografický index a nejbližší dlaždice Microsoft…"):
                data = fetch_microsoft(round(lat, 5), round(lon, 5), radius)
            st.session_state["environment_items"] = data
            st.session_state["environment_site"] = (round(lat, 5), round(lon, 5))
            st.success(f"Microsoft: {len(data)} polygonů poblíž radaru")
        except Exception as exc:
            st.warning(f"Microsoft data se nepodařilo načíst: {str(exc)[:200]}")
    file = st.file_uploader("Import budov / lesů (GeoJSON)", type=["geojson", "json"], key=prefix+"_upload")
    if file is not None and st.button("Použít importovaná data", key=prefix+"_use_import"):
        try:
            if file.size > 60_000_000:
                raise ValueError("GeoJSON je větší než 60 MB. Rozděl ho na menší území.")
            st.session_state["environment_items"] = import_geojson(file.getvalue())
            st.session_state["environment_site"] = None
            st.success("GeoJSON byl načten.")
        except (ValueError, KeyError, TypeError) as exc:
            st.error(f"Neplatný GeoJSON: {exc}")
    items = st.session_state.get("environment_items", [])
    site = st.session_state.get("environment_site")
    if site is not None and site != (round(lat, 5), round(lon, 5)):
        st.warning("Vrstvy jsou načteny pro jiné stanoviště. Proveď nové načtení.")
        return []
    kinds = st.multiselect("Typy objektů", list(COLORS), default=list(COLORS),
                           format_func=lambda k: LABELS[k], key=prefix+"_kinds")
    minimum = st.slider("Minimální známá výška [m]", 0, 200, 0, 5, key=prefix+"_min")
    distance = st.slider("Zobrazit do [km]", 1, 300, 30, 1, key=prefix+"_dist")
    include_unknown = st.checkbox("Zobrazit i neznámé výšky", True, key=prefix+"_unknown")
    az_start, az_end = st.slider("Azimutální sektor [°] (0–360 = vše)",
                                 0, 360, (0, 360), 5, key=prefix+"_az")
    search_name = st.text_input("Hledat objekt podle názvu", "", key=prefix+"_search")
    subset = selected(items, lat, lon, kinds, minimum, distance, include_unknown,
                      az_start, az_end, search_name)
    st.caption(f"Načteno {len(items)} · filtrem vybráno {len(subset)} · "
               f"vykresleno {min(len(subset), MAX_MAP_POLYGONS)} nejbližších objektů")
    st.caption("Výšky bez atributu OSM zůstávají neznámé; nevstupují automaticky do krytí.")
    return subset

def legend_png(items, coverage_layers=None):
    """Compact printable legend, suitable alongside engineering reports."""
    from PIL import Image, ImageDraw, ImageFont
    coverage_layers = coverage_layers or []
    image = Image.new("RGB", (1250, 340 + 30 * len(coverage_layers)), "#0b2132")
    d = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    d.text((35, 25), "COVERAGEDIAGRAMS - ENVIRONMENT / LEGEND", font=font, fill="#e9f7ff")
    y = 82
    for kind, color in COLORS.items():
        d.rectangle((35, y, 59, y+24), fill=color)
        n = sum(x["kind"] == kind for x in items)
        d.text((78, y+5), f"{kind}: {n} polygons", font=font, fill="white")
        y += 53
    unknown = sum(x.get("height_m") is None for x in items)
    for label, color in coverage_layers:
        d.rectangle((35, y, 59, y + 19), fill=color)
        d.text((78, y + 4), str(label), font=font, fill="#ffffff")
        y += 30
    d.text((35, y + 8), f"Unknown heights: {unknown}. Unknown objects not automatically counted as obstacles.", font=font, fill="#b8d4e2")
    d.text((35, y + 34), "Source: OpenStreetMap / imported GeoJSON. Objects are informational overlays unless explicitly applied.", font=font, fill="#b8d4e2")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()

def export_bundle(items, standalone_map_html=None, coverage_layers=None, canopy_overlay=None, airports=None):
    """Reproducible bundle of filtered overlay, legend, citation and optional map."""
    from zipfile import ZipFile, ZIP_DEFLATED
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("environment/environment.geojson", geojson_bytes(items))
        archive.writestr("environment/environment.kml", kml_bytes(items))
        archive.writestr("environment/environment.csv", csv_bytes(items))
        archive.writestr("environment/legend.png", legend_png(items, coverage_layers))
        archive.writestr("environment/README.txt", SOURCES + "\n"
                         + "Height unknown != zero. Filtered overlays do not automatically enter coverage calculations.\n")
        if airports:
            import aviation_layers as aviation
            archive.writestr("aviation/airports.geojson", aviation.geojson_bytes(airports))
            archive.writestr("aviation/airports.kml", aviation.kml_bytes(airports))
            archive.writestr("aviation/airports.csv", aviation.csv_bytes(airports))
        if canopy_overlay is not None:
            raster_png, bounds, minimum, maximum = canopy_overlay
            archive.writestr("environment/canopy_height.png", raster_png)
            archive.writestr("environment/canopy_bounds.json",
                             json.dumps({"bounds_wgs84": bounds, "min_m_agl": minimum,
                                         "max_m_agl": maximum, "note": "Visualization only; source GeoTIFF not included."},
                                        indent=2))
        if standalone_map_html:
            archive.writestr("map/interactive_map.html", standalone_map_html)
    return output.getvalue()
