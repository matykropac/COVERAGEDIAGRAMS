"""VIEWER analysis & printable customer deliverable tools for studio mode."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, A3, A2, A1, A0, landscape, portrait
from reportlab.lib.utils import ImageReader


def render_atlas_pdf(layers, styles, title, *, paper="A3",
                     orientation="landscape", theme="LIGHT",
                     metadata=None, include_statistics=True):
    """Create a multi-page customer atlas, keeping offline imagery claims honest.

    Raster map content is produced by the existing trusted vector-only renderer.
    The atlas pages provide notes and traceable layer names.
    """
    from viewer_export import render_print
    from viewer_coverage_analysis import coverage_stats
    pages={"A4":A4,"A3":A3,"A2":A2,"A1":A1,"A0":A0}
    if paper not in pages:
        raise ValueError("Nepodporovaný formát papíru.")
    if orientation not in ("landscape","portrait"):
        raise ValueError("Neplatná orientace.")
    visible=[(key,features) for key,features in layers.items()
             if styles.get(key,{}).get("show",False)]
    if not visible:raise ValueError("Nejsou zapnuté žádné vrstvy.")
    if len(visible)>200:raise ValueError("Příliš mnoho vrstev pro tiskový atlas.")
    paper_size=landscape(pages[paper]) if orientation=="landscape" else portrait(pages[paper])
    out=io.BytesIO()
    c=canvas.Canvas(out,pagesize=paper_size,pageCompression=1)
    w,h=paper_size
    margin=min(w,h)*.055
    subtitle="COVERAGEDIAGRAMS  |  RADAR COVERAGE ATLAS"
    def txt(value,x,y,size=11):
        c.setFillColorRGB(.12,.2,.3);c.setFont("Helvetica",size)
        c.drawString(x,y,str(value)[:120])
    def header(section):
        c.setFillColorRGB(.06,.16,.25);c.rect(0,h-76,w,76,stroke=0,fill=1)
        c.setFillColorRGB(1,1,1);c.setFont("Helvetica-Bold",18)
        c.drawString(margin,h-44,section[:85])
        c.setFont("Helvetica",9);c.drawRightString(w-margin,h-40,subtitle)
    def footer(page):
        c.setStrokeColorRGB(.7,.75,.8);c.line(margin,margin,w-margin,margin)
        txt("WGS84 source geometries | Vector-only map | Not for navigation",margin,margin-16,8)
        c.setFont("Helvetica",8);c.drawRightString(w-margin,margin-16,f"Page {page}")
    title=(str(title).strip() or "Radar Coverage Atlas")[:120]
    meta=metadata if isinstance(metadata,dict) else {}
    header("RADAR COVERAGE REPORT")
    txt(title,margin,h-125,20)
    txt("Prepared: "+datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),margin,h-165,12)
    txt("Paper: "+paper+" / "+orientation+"   |   Theme: "+theme,margin,h-192,11)
    txt("Visible vector layers: "+str(len(visible)),margin,h-219,11)
    y=h-260
    for key in ("project","radar","location","prepared_by","reference"):
        if meta.get(key):
            txt(key.replace("_"," ").title()+": "+str(meta[key]),margin,y,11);y-=24
    txt("SOURCE & ACCURACY",margin,max(y-34,margin+100),13)
    txt("Coverage polygons are drawn from original input features.",margin,max(y-58,margin+80),10)
    txt("This atlas does not validate RF detection, obstacles, or measured performance.",margin,max(y-78,margin+60),10)
    footer(1);c.showPage()
    header("VECTOR COVERAGE MAP")
    # Render at a bounded resolution; avoid huge untrusted raster allocations on A0.
    png=render_print(layers,styles,title,fmt="png",dpi=300,night=theme=="NIGHT")
    img=ImageReader(io.BytesIO(png));iw,ih=img.getSize()
    maxw=w-2*margin;maxh=h-135-margin
    ratio=min(maxw/iw,maxh/ih)
    rw,rh=iw*ratio,ih*ratio
    c.drawImage(img,(w-rw)/2,margin+35,width=rw,height=rh,mask="auto")
    footer(2);c.showPage()
    if include_statistics:
        header("LAYER STATISTICS & PROVENANCE")
        y=h-105
        txt("Ellipsoidal WGS84 polygon union area; overlaps within each layer removed.",margin,y,10)
        y-=34
        for index,(name,features) in enumerate(visible):
            if y<margin+40:
                footer(3+index);c.showPage();header("LAYER STATISTICS (CONT.)");y=h-105
            try:
                metrics=coverage_stats(features)
                value=f"{metrics['area_km2']:,.2f} km2"
            except (ValueError,TypeError):
                value="N/A (non-polygon or invalid geometry)"
            txt(str(name)[:77],margin,y,10)
            c.setFont("Helvetica",10);c.setFillColorRGB(.12,.2,.3)
            c.drawRightString(w-margin,y,value);y-=19
        footer(3);c.showPage()
    c.save()
    return out.getvalue()


def render_analysis_panel(layers, styles, *, radar_site=None):
    """Independent Streamlit studio controls; no interference with iframe map."""
    import streamlit as st
    from viewer_coverage_analysis import coverage_union, compare_coverage, coverage_stats
    st.markdown("### COVERAGE ANALYSIS")
    candidates=[key for key,fs in layers.items()
                if any((f or {}).get("geometry",{}).get("type")
                       in ("Polygon","MultiPolygon") for f in fs)]
    if not candidates:
        st.info("Pro analýzu načti polygonové radarové vrstvy KML, KMZ nebo GeoJSON.")
        return
    with st.expander("COVERAGE COMPARE · BASELINE / CANDIDATE",expanded=False):
        if len(candidates)<2:
            st.caption("Pro porovnání jsou potřeba alespoň dvě polygonové vrstvy.")
        else:
            a=st.selectbox("Výchozí diagram",candidates,key="studio_compare_a")
            b=st.selectbox("Nový diagram",candidates,index=1,key="studio_compare_b")
            st.caption("Porovnávej stejnou letovou hladinu a referenci AMSL. "
                       "Nekompatibilní podklady mohou dát zavádějící výsledek.")
            confirm=st.checkbox(
                "Potvrzuji stejnou výškovou referenci, FL a kompatibilní geometrii",
                key="studio_compare_confirm")
            if st.button("VYPOČÍTAT PŘEKRYV",key="studio_compare_run",
                         disabled=not confirm):
                try:
                    if a==b:raise ValueError("Zvol dvě různé vrstvy.")
                    import re
                    def fl(name):
                        match=re.search(r"([0-9][0-9\\s]*)\\s*ft\\b",str(name),re.I)
                        return int(match.group(1).replace(" ","")) if match else None
                    fa,fb=fl(a),fl(b)
                    if fa is not None and fb is not None and fa!=fb:
                        raise ValueError("Nelze porovnat rozdílné letové hladiny.")
                    data=compare_coverage(layers[a],layers[b],baseline_name=a,candidate_name=b)
                    st.session_state["studio_compare_result"]=data
                    st.session_state["studio_compare_sources"]=(a,b)
                except Exception as exc:
                    st.error("Porovnání se nezdařilo: "+str(exc))
            result=st.session_state.get("studio_compare_result")
            if result and st.session_state.get("studio_compare_sources")== (a,b):
                metrics=result["metrics"]
                x,y,z=st.columns(3)
                x.metric("Společné [km²]",f"{metrics['common']:,.2f}")
                y.metric("Získané [km²]",f"{metrics['gained']:,.2f}")
                z.metric("Ztracené [km²]",f"{metrics['lost']:,.2f}")
                st.caption("Přesná topologie GEOS; elipsoidické plochy WGS84. "
                           "Pouze geometrické srovnání, nikoliv validační měření.")
                st.download_button("⇩ POROVNÁNÍ · GEOJSON",
                    data=json.dumps({"type":"FeatureCollection",
                                      "features":result["features"]},ensure_ascii=False),
                    file_name="COVERAGE_Compare.geojson",mime="application/geo+json")
    with st.expander("COVERAGE STATISTICS · AZIMUT / RANGE",expanded=False):
        name=st.selectbox("Vrstva pro statistiku",candidates,key="studio_stat_layer")
        use_sectors=st.checkbox("Statistika azimutových sektorů",value=False,key="studio_sector_enabled")
        lat=lon=None;sectors=12;range_nm=100
        if use_sectors:
            initial=radar_site if radar_site else (50.,15.)
            lat=st.number_input("Radar LAT",min_value=-89.,max_value=89.,
                                value=float(initial[0]),format="%.6f",key="studio_sector_lat")
            lon=st.number_input("Radar LON",min_value=-180.,max_value=180.,
                                value=float(initial[1]),format="%.6f",key="studio_sector_lon")
            sectors=st.selectbox("Sektory",options=[4,6,8,12,18,24,36,72],
                                 index=3,key="studio_sector_count")
            range_nm=st.number_input("RANGE [NM]",min_value=1.,max_value=324.,
                                      value=100.,key="studio_sector_range")
        if st.button("SPOČÍTAT STATISTIKU",key="studio_stat_run"):
            try:
                data=coverage_stats(layers[name],radar_lat=lat,radar_lon=lon,
                                    sectors=sectors,range_nm=range_nm if use_sectors else None)
                st.session_state["studio_stats_result"]=(name,data)
            except Exception as exc:st.error(str(exc))
        result=st.session_state.get("studio_stats_result")
        if result and result[0]==name:
            st.metric("Plocha krytí (sjednocené polygony)",f"{result[1]['area_km2']:,.2f} km²")
            if result[1]["sectors"]:
                import pandas as pd
                df=pd.DataFrame(result[1]["sectors"])
                st.bar_chart(df.set_index("az_from")["percent"],
                             x_label="Azimut [°]",y_label="Pokrytí sektoru [%]")
                st.dataframe(df,use_container_width=True,hide_index=True)
            st.download_button("⇩ STATISTIKA · JSON",
                json.dumps(result[1],indent=2,ensure_ascii=False),
                file_name="Coverage_Statistics.json",mime="application/json")
