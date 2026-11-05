"""Presentation-grade, light-themed customer delivery package.

Metrics are area-weighted across the polar model cells. Unknown DEM cells
are not silently classified as uncovered; reported separately. Results are
model estimates, not measured radar performance.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from io import BytesIO, StringIO
from zipfile import ZipFile, ZIP_DEFLATED
import csv
import hashlib
import json
import math

import numpy as np
import radar_core as core

NAVY="#14304c"
BLUE="#246fb2"
CYAN="#278f9e"
PALE="#edf4f9"
MUTED="#587087"
WHITE="#ffffff"


def customer_metrics(result, levels):
    """Actual computed status per FL; sampled area weighting by annular cell area."""
    c=result["config"]
    distances=np.asarray(result["distance"],dtype=float)
    az=np.asarray(result["az"],dtype=float)
    known=np.asarray(result["known"],dtype=bool)
    if known.shape!=(len(az),len(distances)):
        raise ValueError("Mismatch in computed radar grid")
    edges=np.r_[0,(distances[:-1]+distances[1:])/2,
                distances[-1]+(distances[-1]-distances[-2])/2] if len(distances)>1 else np.array([0.,distances[0]])
    # The last bin stops at the modeled range.
    edges[-1]=distances[-1]
    ring_area=(edges[1:]**2-edges[:-1]**2)
    ring_area=np.maximum(0,ring_area)
    weights=np.broadcast_to(ring_area[None,:],known.shape)
    total=float(np.sum(ring_area)*len(az))
    known_area=float(np.sum(weights*known))
    out=[]
    for ft in levels:
        status=np.asarray(core.status_at_height(result,float(ft)*core.FT_TO_M),dtype=float)
        usable=known & np.isfinite(status)
        covered=usable & (status>0)
        observed=float(np.sum(weights*covered))
        out.append({
            "flight_level_ft_amsl":int(ft),
            "coverage_pct_of_known_area":round(100*observed/known_area,2) if known_area else None,
            "coverage_pct_of_total_domain":round(100*observed/total,2) if total else None,
            "known_terrain_pct":round(100*known_area/total,2) if total else None,
            "covered_sample_cells":int(np.count_nonzero(covered)),
            "known_sample_cells":int(np.count_nonzero(known)),
            "total_sample_cells":int(known.size),
        })
    return out


def sector_metrics(result, level, sectors=12):
    """Area-weighted sector breakdown at a selected altitude."""
    known=np.asarray(result["known"],dtype=bool)
    status=np.asarray(core.status_at_height(result,float(level)*core.FT_TO_M),dtype=float)
    dist=np.asarray(result["distance"],dtype=float)
    ring=np.maximum(0,np.diff(np.r_[0.,(dist[:-1]+dist[1:])/2,dist[-1]])) if len(dist)>1 else dist.copy()
    # Use annular area, not radial distance or unweighted sample count.
    edge=np.r_[0.,(dist[:-1]+dist[1:])/2,dist[-1]] if len(dist)>1 else np.array([0.,dist[-1]])
    weights=np.maximum(0,edge[1:]**2-edge[:-1]**2)
    az=np.asarray(result["az"],dtype=float)%360
    rows=[]
    for i in range(sectors):
        lo=i*360/sectors;hi=(i+1)*360/sectors
        mask=(az>=lo)&(az<hi)
        if not np.any(mask):
            continue
        k=known[mask]
        w=np.broadcast_to(weights[None,:],k.shape)
        covered=k&np.isfinite(status[mask])&(status[mask]>0)
        denom=float(np.sum(w*k))
        rows.append({
            "azimuth_start_deg":int(lo),"azimuth_end_deg":int(hi),
            "flight_level_ft_amsl":int(level),
            "coverage_pct_of_known_area":round(100*float(np.sum(w*covered))/denom,2) if denom else None,
        })
    return rows


def _text(ax,x,y,value,size=11,color=NAVY,weight="normal",ha="left",alpha=1):
    ax.text(x,y,str(value),fontsize=size,color=color,fontweight=weight,
            va="center",ha=ha,transform=ax.transAxes,alpha=alpha)


def _background(fig):
    fig.patch.set_facecolor("white")
    ax=fig.add_axes([0,0,1,1]);ax.axis("off")
    ax.add_patch(__import__("matplotlib").patches.Rectangle((0,.945),1,.055,
                 transform=ax.transAxes,facecolor=NAVY,edgecolor="none"))
    _text(ax,.055,.974,"COVERAGEDIAGRAMS  /  CUSTOMER DELIVERY",10,WHITE,"bold")
    return ax


def render_pdf(result,levels,metrics,sectors,project_name):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    c=result["config"]
    buf=BytesIO()
    with PdfPages(buf,metadata={"Title":"Radar Coverage - Customer Technical Summary",
                                "Author":"COVERAGEDIAGRAMS",
                                "Subject":"Modelled radar coverage; not certified measured performance"}) as pdf:
        fig=Figure(figsize=(8.27,11.69),dpi=135,facecolor=WHITE)
        FigureCanvasAgg(fig)
        ax=_background(fig)
        _text(ax,.055,.902,"RADAR COVERAGE",27,NAVY,"bold")
        _text(ax,.055,.867,"Technical summary  /  modelled results",12,MUTED)
        _text(ax,.055,.82,project_name[:85],14,BLUE,"bold")
        values=[
            ("RADAR TYPE",c.radar_mode),
            ("POSITION (WGS84)",f"{c.lat:.6f}, {c.lon:.6f}"),
            ("ANTENNA AGL",f"{c.antenna_agl:.1f} m"),
            ("ANTENNA AMSL",f"{result['antenna']:.1f} m"),
            ("MODEL RANGE",f"{c.range_km:.1f} km / {c.range_km/1.852:.1f} NM"),
            ("ANTENNA TILT",f"{c.antenna_tilt_deg:+.2f} deg"),
            ("MIN / MAX ELEV.",f"{c.min_elev:+.2f} / {c.max_elev:+.2f} deg"),
            ("RADIAL / AZ. STEP",f"{c.step_m:g} m / {c.az_step:g} deg"),
            ("REFRACTION FACTOR",f"k = {c.k:.4f}"),
            ("DATA SOURCE",str(result.get("source","Not recorded"))[:72]),
        ]
        top=.766;row=.036
        ax.add_patch(Rectangle((.055,top-len(values)*row+.006),.89,len(values)*row+.027,
                               transform=ax.transAxes,facecolor=PALE,edgecolor="none"))
        for i,(label,value) in enumerate(values):
            y=top-i*row
            _text(ax,.074,y,label,9,MUTED,"bold")
            _text(ax,.43,y,value,9,NAVY)
        first=metrics[0] if metrics else None
        _text(ax,.055,.365,"FLIGHT-LEVEL COVERAGE SNAPSHOT",13,NAVY,"bold")
        if first:
            ax.add_patch(Rectangle((.055,.263),.89,.080,transform=ax.transAxes,
                                   facecolor="#e7f2fa",edgecolor="none"))
            _text(ax,.077,.315,f"{first['flight_level_ft_amsl']:,} ft AMSL",17,BLUE,"bold")
            pct=first["coverage_pct_of_known_area"]
            _text(ax,.89,.315,f"{pct:.1f}%" if pct is not None else "N/A",
                  22,NAVY,"bold","right")
            _text(ax,.077,.280,"Area-weighted model coverage over known terrain only",9,MUTED)
        _text(ax,.055,.229,f"Exported levels: {len(metrics)}",10,NAVY)
        _text(ax,.055,.200,f"Calculated: {str(result.get('completed_at','Not provided'))[:22]} UTC",10,MUTED)
        _text(ax,.055,.156,"IMPORTANT MODEL LIMITATIONS",10,NAVY,"bold")
        notes=[
            "Coverage is computational, not a measured detection or certification result.",
            "No probability of detection, traffic performance or reliability claim is implied.",
            "Terrain gaps are tracked separately and excluded from known-area coverage.",
            "Heights are AMSL unless otherwise marked; obstacles depend on input quality.",
        ]
        for i,note in enumerate(notes):_text(ax,.055,.129-i*.022,"• "+note,8.1,MUTED)
        _text(ax,.945,.028,"01 / 02",9,MUTED,ha="right")
        pdf.savefig(fig,facecolor="white");fig.clear()

        fig=Figure(figsize=(8.27,11.69),dpi=135,facecolor=WHITE)
        FigureCanvasAgg(fig)
        ax=_background(fig)
        _text(ax,.055,.901,"COVERAGE BY FLIGHT LEVEL",21,NAVY,"bold")
        _text(ax,.055,.871,"Area-weighted, known terrain samples  /  percent",10,MUTED)
        if metrics:
            levels_axis=[str(m["flight_level_ft_amsl"]) for m in metrics]
            pcts=[m["coverage_pct_of_known_area"] or 0 for m in metrics]
            chart=fig.add_axes([.15,.47,.78,.35])
            chart.set_facecolor("white")
            chart.barh(range(len(metrics)),pcts,color=BLUE,height=.65)
            chart.set_yticks(range(len(metrics)),labels=levels_axis,fontsize=7)
            chart.invert_yaxis()
            chart.set_xlim(0,105)
            chart.set_xlabel("Coverage [% of known terrain]",fontsize=9,color=MUTED)
            chart.grid(axis="x",alpha=.18);chart.set_axisbelow(True)
            for i,pct in enumerate(pcts):
                chart.text(min(pct+1.2,102),i,f"{pct:.1f}%",va="center",fontsize=7,color=NAVY)
            chart.spines[["top","right"]].set_visible(False)
        _text(ax,.055,.414,"30-DEGREE SECTOR BREAKDOWN",13,NAVY,"bold")
        _text(ax,.055,.388,f"Reference: {sectors[0]['flight_level_ft_amsl']:,} ft AMSL" if sectors else "No levels selected",10,MUTED)
        for i,entry in enumerate(sectors[:12]):
            col=i//6;row=i%6
            x=.055+col*.46;y=.352-row*.043
            ax.add_patch(Rectangle((x,y-.017),.42,.034,transform=ax.transAxes,
                          facecolor=PALE if row%2==0 else "white",edgecolor="none"))
            _text(ax,x+.01,y,f"{entry['azimuth_start_deg']:03d}–{entry['azimuth_end_deg']:03d}°",9,MUTED,"bold")
            val=entry["coverage_pct_of_known_area"]
            _text(ax,x+.40,y,f"{val:.1f}%" if val is not None else "N/A",10,NAVY,"bold","right")
        _text(ax,.055,.081,"METHOD",10,NAVY,"bold")
        _text(ax,.055,.060,"Polar cells are weighted by annular area; known DEM area is the denominator.",8.1,MUTED)
        _text(ax,.055,.042,"Sector estimates use sampled azimuth bins. Refer to CSV/JSON for exact values.",8.1,MUTED)
        _text(ax,.945,.028,"02 / 02",9,MUTED,ha="right")
        pdf.savefig(fig,facecolor="white");fig.clear()
    return buf.getvalue()


def build_customer_pack(result,flight_levels,project_name="Radar Coverage Study"):
    levels=list(dict.fromkeys(int(ft) for ft in flight_levels))
    if not levels:
        raise ValueError("Choose at least one flight level for the customer package")
    metrics=customer_metrics(result,levels)
    sectors=sector_metrics(result,levels[0])
    csv_data=StringIO()
    columns=list(metrics[0])
    writer=csv.DictWriter(csv_data,fieldnames=columns)
    writer.writeheader();writer.writerows(metrics)
    sec_data=StringIO()
    writer=csv.DictWriter(sec_data,fieldnames=list(sectors[0]) if sectors else [
        "azimuth_start_deg","azimuth_end_deg","flight_level_ft_amsl",
        "coverage_pct_of_known_area"])
    writer.writeheader();writer.writerows(sectors)
    pdf=render_pdf(result,levels,metrics,sectors,project_name)
    metadata={
        "schema":"COVERAGEDIAGRAMS_Customer_Pack_v1",
        "title":project_name,
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "calculation_utc":result.get("completed_at"),
        "config":asdict(result["config"]),
        "model_source":result.get("source",""),
        "metrics":metrics,"sectors":sectors,
        "methodology":{
            "coverage":"Area-weighted fraction of modeled, known-terrain polar cells with status>0",
            "area_weights":"Squared radial bin boundary differences (annular area)",
            "unknown_data":"Missing DEM excluded from known-area denominator, but total-domain metric also given",
            "sector_resolution_deg":30,
            "limitations":"Computational coverage only; not calibrated Pd, detection validation or certification",
        }
    }
    guide=(
        "COVERAGEDIAGRAMS · CUSTOMER DELIVERY / LIGHT EDITION\n"
        "===============================================\n\n"
        f"Project: {project_name}\n"
        "01_Executive_Report.pdf   Two-page light-theme executive and engineering report\n"
        "02_Coverage_By_Flight_Level.csv   Area-weighted coverage per altitude\n"
        "03_Coverage_By_Sector.csv   30-degree azimuth sector summary for first selected FL\n"
        "04_Technical_Metadata.json   Source, assumptions, configuration and results\n"
        "05_SHA256SUMS.txt   Data-integrity hashes of files in this folder\n\n"
        "IMPORTANT: Modelled geometric radar coverage is not detection probability.\n"
        "Unknown terrain is reported separately. These products are not certified charts.\n"
    )
    files={
        "01_Executive_Report.pdf":pdf,
        "02_Coverage_By_Flight_Level.csv":csv_data.getvalue().encode("utf-8-sig"),
        "03_Coverage_By_Sector.csv":sec_data.getvalue().encode("utf-8-sig"),
        "04_Technical_Metadata.json":json.dumps(metadata,indent=2,ensure_ascii=False,
                 allow_nan=False,default=str).encode("utf-8"),
        "README.txt":guide.encode("utf-8"),
    }
    checksum="".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                     for name,data in sorted(files.items()))
    files["05_SHA256SUMS.txt"]=checksum.encode("ascii")
    output=BytesIO()
    with ZipFile(output,"w",ZIP_DEFLATED,compresslevel=6) as z:
        for name,data in files.items():z.writestr("Customer_Pack/"+name,data)
    return output.getvalue()
