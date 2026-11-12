"""Independent spherical-earth, DEM-profile LOS verification.

Deliberately does not call radar_core.apparent_angle(), height_at_angle()
or use result['lower']/result['horizon'] to compute its own line of sight.
Checks the line between radar and target by intersecting its chord with
rays from the effective Earth's center at each sampled geodesic distance.

This checks internal mathematical consistency for a fixed sampled DEM.
It is not an independent terrain dataset, not a measured RF test and cannot
detect hills between DEM sample locations. Unknown terrain -> UNKNOWN.
"""
from __future__ import annotations
import numpy as np


def spherical_chord_clearance(distance_m, ground_amsl_m, antenna_amsl_m,
                              target_amsl_m, k, earth_radius_m=6371008.8):
    """Return actual LOS ray height and clearance above sampled DEM [m].

    The chord between endpoint position vectors on concentric effective-earth
    circles is intersected with the radial ray at each angular ground range.
    Valid for short/medium radar ranges (D/R_eff < pi), no paraxial formula.
    """
    d=np.asarray(distance_m,dtype=np.float64)
    z=np.asarray(ground_amsl_m,dtype=np.float64)
    if d.ndim!=1 or z.ndim!=1 or d.shape!=z.shape or not len(d):
        raise ValueError("Profil vzdálenosti a terénu musí být stejně dlouhé 1D řady.")
    if not np.all(np.isfinite(d)) or not np.isfinite(antenna_amsl_m) or not np.isfinite(target_amsl_m):
        raise ValueError("Neplatné hodnoty vzdálenosti či výšky cíle.")
    if np.any(np.diff(d)<=0) or d[0]<=0:
        raise ValueError("Vzdálenosti musí být kladné a přísně vzestupné.")
    re=float(earth_radius_m)*float(k)
    if not np.isfinite(re) or re<=0 or d[-1]/re>=np.pi:
        raise ValueError("Neplatný efektivní poloměr Země / délka trasy.")
    theta=d/re
    theta_end=theta[-1]
    r0=re+float(antenna_amsl_m)
    rt=re+float(target_amsl_m)
    denom=rt*np.sin(theta_end-theta)+r0*np.sin(theta)
    if np.any(denom<=0):
        raise ValueError("Spojnici nelze pro zadanou geometrii vyhodnotit.")
    ray=r0*rt*np.sin(theta_end)/denom-re
    return ray,ray-z


def verify_radial_point(result, azimuth_index, radial_index, height_m,
                        reference="AMSL", tolerance_m=0.05):
    """Independent geometrical check and solver-versus-check disagreement.

    The reference criterion is direct-sampled LOS plus the same explicitly
    configured min/max elevation. Separately report the original solver's
    geometry mask without trusting that mask to calculate clearance.
    """
    from radar_core import FT_TO_M, apparent_angle
    c=result["config"]
    ai=int(azimuth_index)
    ri=int(radial_index)
    terrain=np.asarray(result["terrain"][ai,:ri+1],dtype=float)
    distance=np.asarray(result["distance"][:ri+1],dtype=float)
    if reference not in ("AMSL","AGL"):
        raise ValueError("Výšková reference musí být AMSL nebo AGL.")
    h_target=(float(height_m) if reference=="AMSL"
              else float(terrain[-1])+float(height_m))
    known=bool(np.all(np.isfinite(terrain))) and bool(result["known"][ai,ri])
    if not known:
        return {"status":"UNKNOWN","reason":"Nedostupný DEM vzorek na trase",
                "distance_m":distance,"terrain_m":terrain,
                "azimuth_deg":float(result["az"][ai]),
                "target_amsl_m":h_target}
    ray,clearance=spherical_chord_clearance(
        distance,terrain,float(result["antenna"]),h_target,c.k)
    # Upper and lower elevation are separate from geometric obstacle LOS.
    angle_deg=float(np.rad2deg(apparent_angle(
        distance[-1],h_target,float(result["antenna"]),c.k)))
    inside_elev=c.min_elev-1e-9<=angle_deg<=c.max_elev+1e-9
    bearing=float(result["az"][ai])
    in_sector=(c.radar_mode!="PAR-NG" or
               abs((bearing-c.bearing_deg+180)%360-180)<=15+1e-8)
    clearance_min=float(np.min(clearance))
    limiting=int(np.argmin(clearance))
    independent_los=clearance_min>=-tolerance_m
    independent_geometry=independent_los and inside_elev and in_sector
    # Compare the original geometric envelope only, not RF detection.
    lower=float(result["lower"][ai,ri])
    upper=float(result["upper"][ai,ri])
    main_geom=np.isfinite(lower) and (
        h_target>=lower-1e-6 and h_target<=upper+1e-6)
    # Obtain the actual final solver outcome at this cell separately.
    from radar_core import status_at_height
    single=dict(result)
    for name in ("terrain","lower","upper","known"):
        single[name]=np.asarray(result[name][ai:ai+1,ri:ri+1])
    single["az"]=np.asarray(result["az"][ai:ai+1])
    single["distance"]=np.asarray(result["distance"][ri:ri+1])
    try:
        final=float(status_at_height(single,float(height_m),reference)[0,0])
    except (ValueError,TypeError,KeyError,IndexError):
        final=float("nan")
    # The independent profile intentionally uses the DEM only. Manually
    # configured obstacles alter the main solver horizon but are not part of
    # this independent terrain raster. Their influence must not be misreported
    # as a mathematical solver error.
    configured_obstacles=bool(result.get("obstacles"))
    status=("OBSTACLES_NOT_CHECKED" if configured_obstacles
            else ("MATCH" if bool(main_geom)==bool(independent_geometry)
                  else "MISMATCH"))
    return {
        "status":status,
        "obstacles_excluded":configured_obstacles,
        "independent_los":bool(independent_los),
        "independent_geometry":bool(independent_geometry),
        "main_geometry":bool(main_geom),
        "final_coverage":final,
        "inside_elevation":bool(inside_elev),
        "inside_sector":bool(in_sector),
        "elevation_deg":angle_deg,
        "minimum_clearance_m":clearance_min,
        "limiting_distance_m":float(distance[limiting]),
        "limiting_terrain_m":float(terrain[limiting]),
        "distance_m":distance,
        "terrain_m":terrain,
        "ray_m":ray,
        "clearance_m":clearance,
        "azimuth_deg":bearing,
        "target_amsl_m":h_target,
        "antenna_amsl_m":float(result["antenna"]),
        "sample_step_m":float(c.step_m),
        "method":"independent spherical chord/radial intersection",
        "limitations":"Same sampled DEM as solver; manual obstacles excluded from independent LOS, no RF validation or sub-grid terrain",
    }
