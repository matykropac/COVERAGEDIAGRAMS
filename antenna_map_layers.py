"""Optional georeferenced visualization of antenna elevation cuts.

AZ wedge is geometric, not a measured azimuth gain pattern.
EL colors represent normalized gain, not validated radar detection/coverage.
"""
from __future__ import annotations
import numpy as np
from pyproj import Geod
import radar_core as core

GEOD=Geod(ellps="WGS84")
COLORS=("#4d6b83","#53afdd","#f4b743","#df674f")

def _point(lat,lon,bearing,distance_m):
    x,y,_=GEOD.fwd(float(lon),float(lat),float(bearing)%360,float(distance_m))
    return [round(float(x),7),round(float(y),7)]

def _sector(lat,lon,bearing,width,r0,r1):
    angles=np.linspace(bearing-width/2,bearing+width/2,17)
    outer=[_point(lat,lon,a,r1) for a in angles]
    if r0<=0:
        inner=[[float(lon),float(lat)]]
    else:
        inner=[_point(lat,lon,a,r0) for a in angles[::-1]]
    return {"type":"Polygon","coordinates":[outer+inner+[outer[0]]]}

def build_layers(config, *, result=None, width_deg=30., bearing_deg=0.,
                 range_nm=20., level_ft=None, show_az=False, show_el=False):
    """Make two independent GeoJSON feature collections on WGS84 coordinates."""
    empty={"type":"FeatureCollection","features":[]}
    az={"type":"FeatureCollection","features":[]}
    el={"type":"FeatureCollection","features":[]}
    width=float(np.clip(width_deg,1.,360.))
    length=float(np.clip(range_nm,1.,260.))*1852.
    lat,lon=float(config.lat),float(config.lon)
    if show_az:
        az["features"].append({"type":"Feature",
            "properties":{"label":"AZ · geometrický sektor (nikoli změřený zisk)",
                          "sector_deg":width},
            "geometry":_sector(lat,lon,bearing_deg,width,0,length)})
    if not show_el or result is None or level_ft is None:
        return az,el
    # Never overlay a stale solution onto an edited radar installation.
    if result.get("config")!=config:
        return az,el
    antenna=float(result["antenna"])
    pattern=result.get("antenna_pattern")
    # Work on a radial, target-altitude cross-section without creating fictitious
    # terrain or claiming a radar coverage solution.
    radii=np.linspace(max(20.,length/140),length,141)
    elevation=core.apparent_angle(radii, np.full_like(radii,float(level_ft)*core.FT_TO_M),
                                  antenna,config.k)
    try:
        if pattern is not None:
            gain=np.asarray(pattern.gain_db(elevation,config.antenna_tilt_deg),dtype=float)
        else:
            gain=10.*np.log10(np.maximum(core.csc_gain(elevation,config),1e-20))
    except (AttributeError,TypeError,ValueError):
        return az,el
    if gain.shape!=radii.shape:
        return az,el
    edges=np.r_[0.,(radii[:-1]+radii[1:])/2.,length]
    last=None
    start=0
    def emit(i,j,bucket):
        if bucket is None:return
        lo=float(edges[i]);hi=float(edges[j])
        if hi<=lo:return
        el["features"].append({"type":"Feature",
            "properties":{"label":"EL · modelový relativní zisk",
                          "gain_band":["< -20 dB","-20 až -10 dB",
                                       "-10 až -3 dB","≥ -3 dB"][bucket],
                          "color":COLORS[bucket],"flight_level_ft":int(level_ft),
                          "not_coverage":True},
            "geometry":_sector(lat,lon,bearing_deg,width,lo,hi)})
    for i,g in enumerate(gain):
        # Outside elevation constraints must not look like a valid measured beam.
        if not np.isfinite(g) or g<=-100 or elevation[i]<np.deg2rad(config.min_elev) or elevation[i]>np.deg2rad(config.max_elev):
            bucket=None
        else:
            bucket=0 if g< -20 else 1 if g< -10 else 2 if g< -3 else 3
        if bucket!=last:
            emit(start,i,last)
            start=i;last=bucket
    emit(start,len(gain),last)
    return az,el
