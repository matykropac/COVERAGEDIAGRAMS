"""Bounded on-demand Microsoft GlobalMLBuildingFootprints tile reader.

Uses official August 2026 dataset-links.csv catalog and gzipped GeoJSONL tiles.
Only a small number of level-9 tiles are requested around a radar site.
This is an optional, best-effort visualization source, NOT surveyed obstacles.
"""
import csv
import gzip
import io
import json
import math
import urllib.parse
import urllib.request

import streamlit as st
from pyproj import Geod
from shapely.geometry import shape, Polygon, box

GEOD = Geod(ellps="WGS84")
CATALOG = "https://bfppub.blob.core.windows.net/%24web/2026-08-13/dataset-links.csv"
MAX_COMPRESSED = 24_000_000
MAX_ITEMS = 12000
MAX_TILE_COUNT = 3

def quadkey(latitude, longitude, zoom=9):
    latitude = max(-85.051128, min(85.051128, float(latitude)))
    longitude = max(-180., min(180., float(longitude)))
    x = int((longitude + 180.) / 360. * (1 << zoom))
    sinlat = math.sin(math.radians(latitude))
    y = int((1. - math.log((1. + sinlat) / (1. - sinlat)) / (2. * math.pi)) / 2. * (1 << zoom))
    x = min((1 << zoom) - 1, max(0, x))
    y = min((1 << zoom) - 1, max(0, y))
    return "".join(str(((x >> i) & 1) + 2 * ((y >> i) & 1)) for i in range(zoom-1, -1, -1))

def _read_url(url, limit):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "bfppub.blob.core.windows.net":
        raise ValueError("Unexpected Microsoft dataset host")
    req = urllib.request.Request(url, headers={"User-Agent": "COVERAGEDIAGRAMS/2.0"})
    with urllib.request.urlopen(req, timeout=35) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Dataset tile/catalog exceeded safe download size")
    return data

@st.cache_data(ttl=24 * 3600, max_entries=2, show_spinner=False)
def tile_catalog():
    table = csv.DictReader(io.StringIO(_read_url(CATALOG, 12_000_000).decode("utf-8-sig")))
    items = {}
    for row in table:
        key = (row.get("QuadKey") or "").strip()
        url = (row.get("Url") or "").strip()
        if len(key) == 9 and set(key) <= set("0123") and url:
            items.setdefault(key, []).append(url)
    if not items:
        raise ValueError("Microsoft catalog format is not recognized")
    return items

def surrounding_quadkeys(lat, lon, radius_km):
    # The search area, not the full dataset, is covered with 9 sampling points.
    # Tiles are deduplicated. Reject locations needing >3 files.
    out = {quadkey(lat, lon)}
    for az in range(0, 360, 45):
        x, y, _ = GEOD.fwd(lon, lat, az, radius_km * 1000)
        out.add(quadkey(y, x))
    if len(out) > MAX_TILE_COUNT:
        raise ValueError("Selected area crosses too many Microsoft tiles; reduce radius")
    return sorted(out)

@st.cache_data(ttl=24 * 3600, max_entries=12, show_spinner=False)
def read_tile(url, lat, lon, radius_km):
    raw = _read_url(url, MAX_COMPRESSED)
    results = []
    # Stream DECOMPRESSION line-by-line, never turn a giant tile into an in-memory list.
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
        for idx, line in enumerate(gz):
            if idx > 500_000:
                raise ValueError("Microsoft tile contains too many records; reduce scope")
            if len(line) > 1_000_000:
                continue
            try:
                record = json.loads(line)
                geometry = record.get("geometry") if record.get("type") == "Feature" else record
                polygon = shape(geometry)
                if polygon.is_empty or polygon.geom_type not in ("Polygon", "MultiPolygon"):
                    continue
                centroid = polygon.centroid
                _, _, metres = GEOD.inv(lon, lat, centroid.x, centroid.y)
                if metres > radius_km * 1000:
                    continue
                # One compact exterior polygon for the interactive map.
                poly = max(polygon.geoms, key=lambda p:p.area) if polygon.geom_type == "MultiPolygon" else polygon
                if len(poly.exterior.coords) > 150:
                    poly = poly.simplify(.000012, preserve_topology=True)
                if poly.geom_type != "Polygon" or len(poly.exterior.coords) > 1200:
                    continue
                coords = [[float(y), float(x)] for x, y in list(poly.exterior.coords)[:-1]]
                if len(coords) < 3:
                    continue
                props = record.get("properties", {}) if record.get("type") == "Feature" else {}
                from environment_layers import _feature
                item = _feature("Building", coords, props, f"ms-{idx}")
                if item:
                    item["source"] = "Microsoft GlobalMLBuildingFootprints (CDLA-Permissive-2.0)"
                    item["height_quality"] = "Microsoft estimate" if item["height_m"] is not None else "unknown"
                    results.append(item)
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            if len(results) >= MAX_ITEMS:
                break
    return results

def fetch_microsoft(lat, lon, radius_km=3.):
    radius_km = float(radius_km)
    if not .5 <= radius_km <= 10:
        raise ValueError("Microsoft fetch radius must be 0.5–10 km")
    catalog = tile_catalog()
    keys = surrounding_quadkeys(lat, lon, radius_km)
    urls = sorted({url for key in keys for url in catalog.get(key, [])})
    if not urls:
        return []
    if len(urls) > MAX_TILE_COUNT:
        raise ValueError(f"Area contains {len(urls)} Microsoft source partitions; reduce radius")
    result = []
    seen = set()
    for url in urls:
        for item in read_tile(url, lat, lon, radius_km):
            key = tuple((round(x, 6), round(y, 6)) for x, y in item["coordinates"][:3])
            if key not in seen:
                result.append(item)
                seen.add(key)
            if len(result) >= MAX_ITEMS:
                return result
    return result
