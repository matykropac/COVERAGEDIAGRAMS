"""10 x 10 m square obstacles, ray-box intersections and terrain-horizon shadowing.

Local east/north metric projection around radar; accurate for site-near obstacles.
Obstacles are independent of polar sampling resolution. Terrain base elevation is
interpolated from sampled DEM; this is an approximation, not a building survey.
"""
import numpy as np
from pyproj import Geod
from radar_core import apparent_angle, height_at_angle

GEOD = Geod(ellps='WGS84')
HALF_SIZE_M = 5.0

def square_corners(lat, lon):
    # Geodetic square corners, aligned to local east/north axes.
    corners = []
    for east, north in ((-5,-5),(-5,5),(5,5),(5,-5)):
        bearing = np.degrees(np.arctan2(east, north))
        x, y, _ = GEOD.fwd(lon, lat, bearing, np.hypot(east, north))
        corners.append([y, x])
    return corners

def intersection(azimuth_deg, east_m, north_m):
    """Entry/exit along ray from origin through 10m square in local EN axes."""
    a = np.radians(azimuth_deg)
    dx, dy = np.sin(a), np.cos(a)
    start, end = 0.0, np.inf
    for origin, direction, center in ((0., dx, east_m), (0., dy, north_m)):
        lo, hi = center - HALF_SIZE_M, center + HALF_SIZE_M
        if abs(direction) < 1e-12:
            if not lo <= origin <= hi:
                return None
        else:
            p, q = (lo-origin)/direction, (hi-origin)/direction
            start = max(start, min(p,q))
            end = min(end, max(p,q))
    return (start,end) if end >= start and end >= 0 else None


def obstacle_signature(obstacles):
    """Stable geometry signature for coverage freshness (labels do not affect physics)."""
    return tuple((o.get('kind', 'point'), o.get('lat'), o.get('lon'),
                  o.get('start_lat'), o.get('start_lon'),
                  o.get('end_lat'), o.get('end_lon'), o['height_m'])
                 for o in obstacles)


def arc_parameters(obstacle, radar_lat, radar_lon):
    """Start bearing, clockwise angular span and endpoint ranges of an arc wall."""
    a1, _, r1 = GEOD.inv(radar_lon, radar_lat,
                         float(obstacle['start_lon']), float(obstacle['start_lat']))
    a2, _, r2 = GEOD.inv(radar_lon, radar_lat,
                         float(obstacle['end_lon']), float(obstacle['end_lat']))
    b1 = a1 % 360.0
    span = ((a2 % 360.0) - b1) % 360.0
    if not (1.0 <= r1 <= 20000.0 and 1.0 <= r2 <= 20000.0):
        raise ValueError('Oba koncové body oblouku musí být 1 m až 20 km od radaru.')
    if not (0.01 < span < 359.99):
        raise ValueError('Úhlový rozsah oblouku musí být mezi 0,01° a 359,99° (po směru hodin).')
    return b1, span, r1, r2


def validate_obstacle(o, radar_lat, radar_lon):
    """Validate both legacy 10×10 m obstacles and clockwise WGS84 arc walls."""
    import math
    kind = o.get('kind', 'point')
    if kind not in ('point', 'arc'):
        raise ValueError('Neznámý typ překážky.')
    height = float(o['height_m'])
    if not math.isfinite(height) or not 0.1 <= height <= 1000.0:
        raise ValueError('Výška překážky musí být 0,1–1000 m AGL.')
    if kind == 'point':
        lat, lon = float(o['lat']), float(o['lon'])
        if not all(math.isfinite(v) for v in (lat, lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError('Neplatné souřadnice bodové překážky.')
        _, _, radius = GEOD.inv(radar_lon, radar_lat, lon, lat)
        if radius > 20000.0:
            raise ValueError('Překážky jsou podporovány nejvýše 20 km od radaru.')
    else:
        for key, limit in (('start_lat', 90), ('start_lon', 180),
                           ('end_lat', 90), ('end_lon', 180)):
            val = float(o[key])
            if not math.isfinite(val) or not -limit <= val <= limit:
                raise ValueError('Neplatné souřadnice konce/začátku oblouku.')
        arc_parameters(o, radar_lat, radar_lon)


def obstacle_polygon(obstacle, radar_lat, radar_lon):
    """Map footprint [lat, lon] of point (square) or 10 m wide clockwise arc."""
    if obstacle.get('kind', 'point') == 'point':
        return square_corners(obstacle['lat'], obstacle['lon'])
    bearing, span, r1, r2 = arc_parameters(obstacle, radar_lat, radar_lon)
    n = max(2, int(np.ceil(span / 1.0)) + 1)
    fraction = np.linspace(0., 1., n)
    azimuth = bearing + span * fraction
    radius = r1 + (r2-r1) * fraction
    outer_lon, outer_lat, _ = GEOD.fwd(
        np.full(n, radar_lon), np.full(n, radar_lat),
        azimuth, radius + HALF_SIZE_M)
    inner_lon, inner_lat, _ = GEOD.fwd(
        np.full(n, radar_lon), np.full(n, radar_lat),
        azimuth[::-1], np.maximum(1.0, radius[::-1]-HALF_SIZE_M))
    return [[float(y), float(x)] for y, x in
            zip(np.r_[outer_lat, inner_lat], np.r_[outer_lon, inner_lon])]

def apply_obstacles(result, obstacles):
    """Apply obstacle-top horizon to previously solved terrain visibility in place."""
    result['obstacles'] = [dict(o) for o in obstacles]
    if not obstacles:
        return result
    c = result['config']
    if len(obstacles) > 100:
        raise ValueError('Nejvýše 100 překážek.')
    az, distances = result['az'], result['distance']
    horizon = result['horizon'].copy()
    lower = result['lower'].copy()
    valid = result['known']
    for o in obstacles:
        validate_obstacle(o, c.lat, c.lon)
        h = float(o['height_m'])
        kind = o.get('kind', 'point')
        if kind == 'arc':
            b_start, span, r_start, r_end = arc_parameters(o, c.lat, c.lon)
        else:
            bearing, _, radius = GEOD.inv(c.lon, c.lat, float(o['lon']), float(o['lat']))
            ea = radius*np.sin(np.radians(bearing))
            no = radius*np.cos(np.radians(bearing))
        for j, bearing_ray in enumerate(az):
            if kind == 'arc':
                clockwise = (float(bearing_ray) - b_start) % 360.0
                if clockwise > span + 1e-8:
                    continue
                radius_on_ray = r_start + (r_end-r_start) * (clockwise/span)
                entry = max(0.0, radius_on_ray-HALF_SIZE_M)
            else:
                cut = intersection(bearing_ray, ea, no)
                if cut is None:
                    continue
                entry, _ = cut
            if entry >= distances[-1]:
                continue
            # Terrain at the obstacle is interpolated from the polar DEM.
            samples = result['terrain'][j]
            finite = np.isfinite(samples)
            if not finite.any():
                continue
            ground = np.interp(max(entry, 0.), distances[finite], samples[finite])
            top = ground + h
            angle = float(apparent_angle(max(entry, .01), top, result['antenna'], c.k))
            impacted = distances >= entry
            horizon[j, impacted] = np.maximum(horizon[j, impacted], angle)
    new_lower = height_at_angle(distances[None,:], np.maximum(horizon, np.deg2rad(c.min_elev)),
                                result['antenna'], c.k)
    lower = np.maximum(lower, new_lower)
    lower[~valid | (lower > result['upper'])] = np.nan
    result['lower'] = lower
    result['horizon'] = horizon
    old = result['status']
    survives = result['target'] >= lower - 1e-6
    result['status'] = np.where(valid, (np.nan_to_num(old, nan=0.) > 0) & survives, np.nan).astype(float)
    return result
