"""Bridge automatically loaded surrounding geodata into editable obstacles.

Keep every source item in the catalog, including unknown heights. Only known,
validated footprints can enter the radar solver (max 1000 total). Unknown
heights must never be silently replaced by fabricated values.
"""
import hashlib
import math

from obstacles import square_corners, validate_obstacle
from environment_layers import numeric_height

MAX_ACTIVE = 1000


def _identity(prefix, source, source_id, coordinates):
    identifier = str(source_id or "").strip()
    if not identifier:
        identifier = hashlib.sha1(repr(coordinates).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{source}:{identifier}"


def _valid_height(raw):
    if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
        h=float(raw)
        return h if .1 <= h <= 1000 else None
    return numeric_height(raw)


def catalog_from_data(environment, wind):
    """Make one editable catalog without dropping no-height objects."""
    entries=[]
    seen=set()
    for item in environment:
        coords=item.get("coordinates") or []
        source=str(item.get("source") or "OSM")
        identifier=_identity("env",source,item.get("source_id"),coords)
        if identifier in seen:continue
        seen.add(identifier)
        entries.append({
            "id":identifier,"name":str(item.get("name") or "Objekt")[:130],
            "category":str(item.get("kind") or "Building"),
            "coordinates":coords,"height_m":_valid_height(item.get("height_m")),
            "source":source,"height_quality":str(item.get("height_quality") or "unknown"),
            "enabled":False,
        })
    for item in wind:
        lat=item.get("lat");lon=item.get("lon")
        try:
            lat=float(lat);lon=float(lon)
            if not (-90<=lat<=90 and -180<=lon<=180):
                continue
        except (ValueError,TypeError):
            continue
        identifier=_identity("wind","wind",item.get("osm_id"),[lat,lon])
        if identifier in seen:continue
        seen.add(identifier)
        h=_valid_height(item.get("height"))
        entries.append({
            "id":identifier,"name":str(item.get("name") or "Větrná elektrárna")[:130],
            "category":"Wind","coordinates":square_corners(lat,lon),
            "height_m":h,"source":"Wind dataset / OSM",
            "height_quality":"dataset height" if h is not None else "unknown",
            "enabled":False,
        })
    return entries


def _to_obstacle(entry):
    return {
        "kind":"polygon","name":entry["name"],
        "coordinates":entry["coordinates"],"height_m":entry["height_m"],
        "catalog_id":entry["id"],
        "source":entry["source"],
    }


def synchronize(existing_obstacles, catalog, lat, lon, *, auto_enable=False):
    """Reconcile the imported catalog with manual and previous active items.

    On first load, automatically enable valid known-height items up to the
    solver cap. Later manual deletions/edits stay respected on every rerun.
    """
    manual=[x for x in existing_obstacles if not x.get("catalog_id")]
    active=[]
    errors=0
    limit=max(0,MAX_ACTIVE-len(manual))
    for entry in catalog:
        if auto_enable:
            if entry.get("height_m") is not None and len(active)<limit:
                entry["enabled"]=True
        if not entry.get("enabled"):
            continue
        item=_to_obstacle(entry)
        try:
            validate_obstacle(item,lat,lon)
        except (ValueError,KeyError,TypeError):
            entry["enabled"]=False
            errors+=1
            continue
        if len(active)>=limit:
            entry["enabled"]=False
            errors+=1
            continue
        active.append(item)
    return manual+active,errors
