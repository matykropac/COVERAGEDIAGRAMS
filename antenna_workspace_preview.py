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
