"""Portable PAR scan diagnostics for one requested flight level.

All masks originate in the same DEM, horizon and angular RF model that
the map uses; no synthetic tiles or full-model recomputation. The output
clearly marks assumptions and uncalibrated channel behavior.
"""
from __future__ import annotations
from dataclasses import asdict
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
import json
import numpy as np


def _mask_geojson(result, mask, label):
    from pyproj import Transformer
    from shapely.geometry import mapping
    from shapely.ops import transform
    import radar_core as core
    crs=Transformer.from_crs(core.local_crs(result["config"]),
                             "EPSG:4326",always_xy=True)
    return {"type":"FeatureCollection","name":label,"features":[
        {"type":"Feature","geometry":mapping(transform(crs.transform,poly)),
         "properties":{"name":label,"model":"preliminary Y8600 AESA simulation"}}
        for poly in core.coverage_polygons(result,mask)]}


def make_diagnostics_zip(result, altitude_ft, *, reference="AMSL"):
    import radar_core as core
    if result["config"].radar_mode!="PAR-NG":
        raise ValueError("Diagnostika AESA je dostupná pouze pro PAR-NG.")
    if not core.valid_flight_level("PAR-NG",altitude_ft):
        raise ValueError("Neplatná referenční výška.")
    if reference not in ("AMSL","AGL"):
        raise ValueError("Výška musí být AMSL nebo AGL.")
    pattern=result["antenna_pattern"]
    diagnostic=core.par_channel_status_at_height(
        result,altitude_ft*core.FT_TO_M,reference)
    both=diagnostic["both"]
    limiter=diagnostic["limiting_channel"]
    # Separate limiting-zone contours, restricted to joint coverage.
    limiter_az=np.where(np.isnan(both),np.nan,((both==1)&(limiter==0)).astype(float))
    limiter_el=np.where(np.isnan(both),np.nan,((both==1)&(limiter==1)).astype(float))
    layers={
        "01_AZ_coverage":diagnostic["az"],
        "02_EL_coverage":diagnostic["el"],
        "03_JOINT_coverage":both,
        "04_limit_AZ":limiter_az,
        "05_limit_EL":limiter_el,
    }
    manifest={
        "format":"COVERAGEDIAGRAMS PAR AESA DIAGNOSTICS",
        "altitude_ft":int(altitude_ft),"reference":reference,
        "mode":pattern.coverage_mode,
        "active_channel":pattern.channel_mode,
        "pattern_source":pattern.name,
        "pattern_sha256":pattern.source_sha256,
        "pattern_calibration":"not verified",
        "EL_pattern":"analytic Gaussian, NOT measured",
        "scan_schedule":"provisional uniform beam commands",
        "propagation":"effective earth, terrain line of sight; user-entered gas/rain dB/km",
        "limitations":"Not a certified Pd map. No measured EL gain, absolute channel RF budget, diffraction or clutter.",
        "radar":asdict(result["config"]),
    }
    out=BytesIO()
    with ZipFile(out,"w",ZIP_DEFLATED,compresslevel=5) as z:
        z.writestr("README_parameters.json",json.dumps(manifest,ensure_ascii=False,indent=2))
        for name,mask in layers.items():
            collection=_mask_geojson(result,mask,name)
            z.writestr("layers/"+name+".geojson",
                       json.dumps(collection,ensure_ascii=False,separators=(",",":")))
        buffer=BytesIO()
        np.savez_compressed(buffer,
            azimuth_deg=np.asarray(result["az"],dtype=np.float32),
            radial_distance_m=np.asarray(result["distance"],dtype=np.float32),
            az_margin_db=np.asarray(diagnostic["az_margin_db"],dtype=np.float32),
            el_margin_db=np.asarray(diagnostic["el_margin_db"],dtype=np.float32),
            limiting_margin_db=np.asarray(diagnostic["limiting_margin_db"],dtype=np.float32),
            limiting_channel=np.asarray(limiter,dtype=np.float32))
        z.writestr("data/par_channel_margins.npz",buffer.getvalue())
    return out.getvalue()
