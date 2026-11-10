"""Read-only, engineering-linked antenna elevation preview.

Uses the exact antenna pattern object selected by COVERAGEDIAGRAMS for its
coverage calculation. Nothing here modifies calibration or RF calculations.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import radar_core as core


def antenna_figure(config, pattern):
    """Create a responsive elevation-cut chart with measured/model provenance."""
    low=max(-15.,float(config.min_elev),-90.)
    high=min(90.,float(config.max_elev))
    if high <= low:
        raise ValueError("Maximální elevace musí být větší než minimální.")
    angles=np.linspace(low,high,1000)
    radians=np.deg2rad(angles)
    tilt=float(config.antenna_tilt_deg)
    fig=go.Figure()
    if isinstance(pattern,core.AntennaPatternPair):
        low_db,high_db=pattern.channel_gain_db(radians,tilt)
        series=(("LOW · Tx/Rx",low_db,"#63c9ef"),
                ("HIGH · Rx only",high_db,"#f8c56f"))
        provenance="RL-2000 · Y7252 typical (digitized engineering approximation)"
        source="Typical normalized elevation cuts; not site-calibrated measurements."
    else:
        gains=pattern.gain_db(radians,tilt)
        series=(("Vertical cut",gains,"#63c9ef"),)
        if config.radar_mode=="SSR" and "Measured" in type(pattern).__name__:
            provenance="SSR.txt · measured relative elevation cut"
            source="Relative measured cut normalized to peak. Absolute gain and RF link margins remain model assumptions."
        elif config.radar_mode=="SSR":
            provenance="SSR · Gaussian reference model"
            source="Analytical model; not a calibrated or measured antenna diagram."
        elif config.radar_mode=="PAR-NG":
            provenance="PAR-NG · supplied 3D gain grid / azimuth 0°"
            source="Embedded 9 GHz gain-grid input; not certified site calibration."
        else:
            provenance="Antenna model used by the coverage engine"
            source="Normalized model input; calibration status not established."
    for label,values,color in series:
        values=np.asarray(values,dtype=float)
        values=np.where(np.isfinite(values),values,np.nan)
        # Clip for a readable operational plot without misrepresenting floor values.
        values=np.maximum(values,-80.)
        fig.add_trace(go.Scatter(
            x=angles,y=values,name=label,mode="lines",
            line=dict(width=2.4,color=color),
            hovertemplate="Elevation %{x:.2f}°<br>Relative gain %{y:.2f} dB<extra>%{fullData.name}</extra>",
        ))
    fig.add_vline(x=tilt,line=dict(color="#f18498",width=1.3,dash="dot"),
                  annotation_text="TILT",annotation_position="top right",
                  annotation_font=dict(color="#f7b0bc",size=10))
    fig.update_layout(
        template="plotly_dark",height=350,
        paper_bgcolor="#0e2237",plot_bgcolor="#0e2237",
        margin=dict(l=57,r=18,t=30,b=76),
        font=dict(color="#c9dfed",size=11),
        legend=dict(orientation="h",y=-.29,x=0,
                    bgcolor="rgba(0,0,0,0)",font=dict(size=10)),
        xaxis=dict(title=dict(text="Elevation [°]",font=dict(size=11)),
                   range=[low,high],gridcolor="#29445c",zerolinecolor="#51718a",
                   tickfont=dict(size=10)),
        yaxis=dict(title=dict(text="Relative gain [dB]",font=dict(size=11)),
                   range=[-80,4],gridcolor="#29445c",zerolinecolor="#51718a",
                   tickfont=dict(size=10)),
        hovermode="x unified",
    )
    return fig,provenance,source


def par_3d_figure(pattern, *, near_field=False):
    """Display the actual embedded PAR-NG 3D gain grid, not an invented beam.

    Downsample for browser responsiveness, retain original full-resolution data
    in the engine. 0 dB is global pattern peak, not absolute dBi.
    """
    if not isinstance(pattern,core.ParScanPattern):
        raise TypeError("3D PAR diagram requires ParScanPattern.")
    az=np.asarray(pattern.azimuths_deg)
    el=np.asarray(pattern.angles_deg)
    grid=np.asarray(pattern.gain_grid_db)
    if grid.shape!=(len(el),len(az)):
        raise ValueError("PAR diagram has inconsistent grid dimensions.")
    ei=np.arange(0,len(el),2,dtype=int)
    ai=np.arange(0,len(az),2,dtype=int)
    if ei[-1]!=len(el)-1:ei=np.r_[ei,len(el)-1]
    if ai[-1]!=len(az)-1:ai=np.r_[ai,len(az)-1]
    fig=go.Figure(go.Heatmap(
        x=az[ai],y=el[ei],z=np.maximum(grid[np.ix_(ei,ai)],-80),
        colorscale=[[0,"#10243b"],[.25,"#275477"],[.5,"#287eaa"],
                    [.72,"#39a8c7"],[.9,"#82dce0"],[1,"#ffe3a0"]],
        zmin=-80,zmax=0,
        colorbar=dict(title=dict(text="Relative gain [dB]",side="right"),
                      tickfont=dict(color="#c9dfed",size=10),
                      thickness=13,len=.75),
        hovertemplate="Azimuth %{x:.1f}°<br>Elevation %{y:.1f}°"
                      "<br>Relative gain %{z:.1f} dB<extra></extra>",
    ))
    fig.add_vline(x=0,line=dict(color="#ffc77d",dash="dot",width=1))
    fig.add_hline(y=0,line=dict(color="#ffc77d",dash="dot",width=1))
    fig.update_layout(
        template="plotly_dark",height=360,
        paper_bgcolor="#0e2237",plot_bgcolor="#0e2237",
        margin=dict(l=55,r=12,t=12,b=52),
        font=dict(color="#c9dfed",size=10),
        xaxis=dict(title="Relative azimuth [°]",gridcolor="#29445c",
                   range=[-20,20] if near_field else [-180,180]),
        yaxis=dict(title="Elevation [°]",gridcolor="#29445c",
                   range=[-15,50] if near_field else [-90,90]),
    )
    return fig


def par_pattern_info(pattern):
    """Provenance from actual imported source, with units never conflated."""
    if not isinstance(pattern,core.ParScanPattern):
        raise TypeError("Requires PAR 3D pattern.")
    return {
        "file":pattern.name,
        "sha256":pattern.source_sha256,
        "samples":int(pattern.gain_grid_db.size),
        "elevation_samples":len(pattern.angles_deg),
        "azimuth_samples":len(pattern.azimuths_deg),
        "source_peak_db":pattern.source_peak_db,
        "relative_max_db":float(np.max(pattern.gain_grid_db)),
        "elevation_step_deg":float(np.median(np.diff(pattern.angles_deg))),
        "azimuth_step_deg":float(np.median(np.diff(pattern.azimuths_deg))),
    }


def par_scanned_coverage_figure(pattern, *, reference_range_km=40.0):
    """Operational scan-envelope visualization, NOT the raw static gain grid.

    Every pixel uses a nearest commanded AZ/EL steering position, directional
    gain and optional steering loss; the channel combination matches the
    solver's independent range-factor logic.
    """
    if not isinstance(pattern,core.ParScanPattern):
        raise TypeError("PAR scanning preview requires ParScanPattern.")
    az=np.linspace(-15.,15.,151)
    el=np.linspace(-1.,14.,101)
    az_grid,el_grid=np.meshgrid(az,el,indexing="xy")
    factor=pattern.effective_range_factor(np.deg2rad(el_grid),az_grid)
    # Display maximum nominal slant range in km, capped by instrumental range.
    nominal=np.minimum(reference_range_km,reference_range_km*factor)
    fig=go.Figure(go.Heatmap(
        x=az,y=el,z=np.round(nominal,2),
        zmin=0,zmax=reference_range_km,
        colorscale=[[0,"#14283f"],[.25,"#1d5478"],[.5,"#32799b"],
                    [.75,"#49b2ce"],[1,"#a8e8da"]],
        colorbar=dict(title=dict(text="Reference reach [km]",side="right"),
                      thickness=12,len=.77),
        hovertemplate="AZ %{x:.2f}°<br>EL %{y:.2f}°"
                      "<br>Modeled reach %{z:.2f} km<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_dark",height=315,margin=dict(l=55,r=14,t=12,b=55),
        paper_bgcolor="#0e2237",plot_bgcolor="#0e2237",
        font=dict(color="#c9dfed",size=10),
        xaxis=dict(title="Relative azimuth [°]",gridcolor="#29445c"),
        yaxis=dict(title="Elevation [°]",gridcolor="#29445c"),
    )
    return fig
