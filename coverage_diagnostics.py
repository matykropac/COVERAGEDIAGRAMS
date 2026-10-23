"""Engineering diagnostics for radar line-of-sight coverage.

This module evaluates the exact native polar samples produced by radar_core.
It never invents interpolated azimuths or labels unknown DEM as covered.
"""
from dataclasses import dataclass
import numpy as np
from pyproj import Geod
import radar_core as core
from obstacles import arc_parameters, intersection

GEOD = Geod(ellps="WGS84")


def native_azimuth(result, selected_deg):
    """Return (radial index, native bearing, inside scan sector)."""
    c = result["config"]
    idx, inside = core.azimuth_indices(result["az"], c, float(selected_deg))
    idx = int(np.asarray(idx).item())
    return idx, float(result["az"][idx] % 360), bool(np.asarray(inside).item())


def obstacle_intersections(result, index):
    """Obstacle tops intersecting the selected native radial, with approximate DEM bases."""
    c = result["config"]
    bearing = float(result["az"][index] % 360)
    distances = result["distance"]
    terrain = result["terrain"][index]
    finite = np.isfinite(terrain)
    if not finite.any():
        return []
    hits = []
    for number, item in enumerate(result.get("obstacles", []), 1):
        if item.get("kind", "point") == "arc":
            start, span, r1, r2 = arc_parameters(item, c.lat, c.lon)
            fraction = ((bearing - start) % 360) / span
            if not 0 <= fraction <= 1:
                continue
            distance = r1 + (r2-r1) * fraction - 5.0
        else:
            az, _, radius = GEOD.inv(c.lon, c.lat, float(item["lon"]), float(item["lat"]))
            east = radius * np.sin(np.deg2rad(az))
            north = radius * np.cos(np.deg2rad(az))
            contact = intersection(bearing, east, north)
            if contact is None:
                continue
            distance = contact[0]
        distance = max(0.01, float(distance))
        if distance > distances[-1]:
            continue
        # Obstacle base: interpolation of the same sampled DEM, not a surveyed height.
        base = float(np.interp(distance, distances[finite], terrain[finite]))
        top = base + float(item["height_m"])
        if not np.isfinite(top):
            continue
        hits.append(dict(
            name=str(item.get("name") or "Překážka %02d" % number),
            kind="obstacle", distance_m=distance, base_m=base, top_m=top,
            angle_deg=float(np.rad2deg(core.apparent_angle(
                distance, top, result["antenna"], c.k)))))
    return sorted(hits, key=lambda hit: hit["distance_m"])


def limiting_object(result, index, range_index):
    """Highest apparent obstruction on a radar-to-target radial, including entered objects."""
    distances = result["distance"]
    terrain = result["terrain"][index, :range_index+1]
    if not np.isfinite(terrain).all():
        return None
    angles = np.rad2deg(core.apparent_angle(
        distances[:range_index+1], terrain, result["antenna"], result["config"].k))
    max_index = int(np.argmax(angles))
    blocker = dict(name="Terén (DEM)", kind="terrain",
                   distance_m=float(distances[max_index]),
                   base_m=float(terrain[max_index]), top_m=float(terrain[max_index]),
                   angle_deg=float(angles[max_index]))
    for hit in obstacle_intersections(result, index):
        if hit["distance_m"] <= float(distances[range_index]) and hit["angle_deg"] > blocker["angle_deg"]:
            blocker = hit
    return blocker


def diagnose(result, azimuth_deg, distance_km, height_ft):
    """Explain independent limiting factors at a selected point/nominal AMSL height.

    Does not claim a probability of detection. Returns the actual sampled range
    and azimuth; an unsupported PAR bearing is explicitly outside the scan.
    """
    index, bearing, inside = native_azimuth(result, azimuth_deg)
    distances = result["distance"]
    requested_m = float(distance_km) * 1000.0
    if not inside or requested_m < distances[0] / 2 or requested_m > distances[-1]:
        return dict(state="outside", causes=["Mimo vypočtený sektor nebo dosah"],
                    azimuth_deg=bearing, requested_deg=float(azimuth_deg), index=index)
    j = int(np.argmin(np.abs(distances - requested_m)))
    d = float(distances[j])
    height = float(height_ft) * core.FT_TO_M
    c = result["config"]
    record = dict(index=index, range_index=j, requested_deg=float(azimuth_deg),
                  azimuth_deg=bearing, distance_km=d / 1000.0,
                  height_ft=float(height_ft), height_m=height)
    if not bool(result["known"][index, j]):
        record.update(state="unknown", causes=["Neúplná data DEM na trase"],
                      blocker=None)
        return record

    blocker = limiting_object(result, index, j)
    apparent = float(np.rad2deg(core.apparent_angle(d, height, result["antenna"], c.k)))
    slant_km = float(core.slant_distance(d, height, result["antenna"], c.k)) / 1000.0
    terrain_here = float(result["terrain"][index, j])
    causes = []
    # Report multiple simultaneous causes rather than guessing a single one.
    if height < terrain_here - 1e-6:
        causes.append("Hladina leží pod místním terénem")
    if blocker is not None and apparent < blocker["angle_deg"] - 1e-5:
        causes.append("Stín zadané překážky" if blocker["kind"] == "obstacle"
                      else "Terénní stín (DEM)")
    if apparent < c.min_elev - 1e-5:
        causes.append("Pod minimální elevací antény")
    if apparent > c.max_elev + 1e-5:
        causes.append("Nad maximální elevací antény")

    envelope_km = None
    if c.csc_enabled:
        gain = (core.pattern_range_factor(result["antenna_pattern"],
                                          np.deg2rad(apparent), c)
                if result.get("antenna_pattern") is not None else
                np.sqrt(float(core.csc_gain(np.deg2rad(apparent), c))))
        envelope_km = float(c.csc_range_km * gain)
        if slant_km > envelope_km + 1e-5:
            causes.append("Mimo dosah daný vyzařovacím diagramem / bilancí")

    status = core.status_at_height(result, height)[index, j]
    state = "covered" if status == 1 else "blocked"
    if state == "blocked" and not causes:
        causes.append("Geometrická hranice modelu / rozlišení vzorkování")
    lon, lat, _ = GEOD.fwd(c.lon, c.lat, bearing, d)
    if blocker is not None:
        b_lon, b_lat, _ = GEOD.fwd(c.lon, c.lat, bearing, blocker["distance_m"])
        blocker = dict(blocker, lat=float(b_lat), lon=float(b_lon),
                       clearance_m=float(height - core.height_at_angle(
                           d, np.deg2rad(blocker["angle_deg"]),
                           result["antenna"], c.k)))
    record.update(state=state, causes=causes, blocker=blocker,
                  apparent_deg=apparent, slant_km=slant_km,
                  allowed_slant_km=envelope_km, terrain_m=terrain_here,
                  lat=float(lat), lon=float(lon))
    return record


def azimuth_coverage_stats(result, height_ft, min_km=0.0, max_km=None):
    """Area-weighted native radial coverage percentages; missing DEM excluded.

    Annular sample weights avoid overemphasizing the short inner range.
    Unknown share is reported relative to the entire selected domain.
    """
    distances = result["distance"]
    max_km = float(distances[-1] / 1000) if max_km is None else float(max_km)
    selected = (distances >= float(min_km)*1000) & (distances <= max_km*1000)
    if not np.any(selected):
        raise ValueError("Rozsah analýzy neobsahuje žádný vypočtený vzorek.")
    ends = distances[selected]
    prev = np.r_[max(0.0, float(min_km)*1000), ends[:-1]]
    weight = np.maximum(0.0, ends**2 - prev**2)
    if not np.any(weight):
        weight = np.ones_like(ends)
    status = core.status_at_height(result, float(height_ft)*core.FT_TO_M)[:, selected]
    known = np.isfinite(status)
    total = float(weight.sum())
    output = []
    for idx, bearing in enumerate(result["az"]):
        known_area = float(np.sum(weight * known[idx]))
        covered_area = float(np.sum(weight * (status[idx] == 1)))
        output.append(dict(azimuth_deg=float(bearing % 360),
                           covered_pct=round(100*covered_area/known_area, 2)
                           if known_area else None,
                           unknown_pct=round(100*(1-known_area/total), 2)))
    return output
