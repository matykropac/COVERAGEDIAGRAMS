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
        lat, lon, h = float(o['lat']), float(o['lon']), float(o['height_m'])
        if not (-90<=lat<=90 and -180<=lon<=180 and .1<=h<=1000):
            raise ValueError('Neplatné souřadnice nebo výška překážky.')
        bearing, _, radius = GEOD.inv(c.lon,c.lat,lon,lat)
        if radius > 20000:
            raise ValueError('Překážky jsou podporovány nejvýše 20 km od radaru.')
        ea = radius*np.sin(np.radians(bearing))
        no = radius*np.cos(np.radians(bearing))
        for j, bearing_ray in enumerate(az):
            cut = intersection(bearing_ray, ea, no)
            if cut is None:
                continue
            entry, exit_distance = cut
            if entry >= distances[-1]:
                continue
            # Ground at obstacle estimated on this ray from existing polar DEM.
            probe = max(entry, 0.)
            samples = result['terrain'][j]
            finite = np.isfinite(samples)
            if not finite.any():
                continue
            ground = np.interp(probe, distances[finite], samples[finite])
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
